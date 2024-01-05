import io
import boto3
import pandas as pd
from fpdf import FPDF
from PIL import Image
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# Set up AWS credentials
# Replace with your actual credentials


# -----------dummy credentials-----------
# AWS_ACCESS_KEY_ID ='AKIATTWE4TOCJJKUAIV4',
# AWS_SECRET_ACCESS_KEY ='l6NeL56Cd/dSN++XMU825CO5FmhzU7N3+rUvdVG4',
# AWS_REGION_NAME ='ap-south-1'


# --------------Set up AWS credentials------------
# -----------------Replace with your actual credentials------------
AWS_ACCESS_KEY_ID = 'YOUR_ACCESS_KEY_ID'
AWS_SECRET_ACCESS_KEY = 'YOUR_SECRET_ACCESS_KEY'
AWS_REGION_NAME = 'YOUR_REGION_NAME'

# Initialize the Textract client
session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION_NAME
)
client = session.client('textract')

# ------handle landingpage route----
@app.route('/')
def index():
    return render_template('FrontEnd.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    file = request.files['file']
 
    # Save the file to a BytesIO buffer
    buffer = io.BytesIO()
    file.save(buffer)
    buffer.seek(0)

    try:
        if file.filename.endswith('.pdf'):
            response = client.analyze_document(
                Document={
                    'Bytes': buffer.getvalue()
                },
                FeatureTypes=['TABLES']
            )
        else:
            # Open image file with PIL
            image = Image.open(buffer)
            # Convert the image to PNG format
            png_buffer = io.BytesIO()
            image.save(png_buffer, format='PNG')
            png_buffer.seek(0)
            response = client.analyze_document(
                Document={
                    'Bytes': png_buffer.getvalue()
                },
                FeatureTypes=['TABLES']
            ) 
        def map_blocks(blocks, block_type):
            return {
                block['Id']: block
                for block in blocks
                if block['BlockType'] == block_type
            }

        blocks = response['Blocks']
        tables = map_blocks(blocks, 'TABLE')
        cells = map_blocks(blocks, 'CELL')
        words = map_blocks(blocks, 'WORD')
        selections = map_blocks(blocks, 'SELECTION_ELEMENT')

        def get_children_ids(block):
            for rels in block.get('Relationships', []):
                if rels['Type'] == 'CHILD':
                    yield from rels['Ids']


        dataframes = []
        for table in tables.values():

            # Determine all the cells that belong to this table
            table_cells = [cells[cell_id] for cell_id in get_children_ids(table)]
        
            # Determine the table's number of rows and columns
            n_rows = max(cell['RowIndex'] for cell in table_cells)
            n_cols = max(cell['ColumnIndex'] for cell in table_cells)
            content = [[None for _ in range(n_cols)] for _ in range(n_rows)]
            
            # Fill in each cell
            for cell in table_cells:
                cell_contents = [
                    words[child_id]['Text']
                    if child_id in words
                    else selections[child_id]['SelectionStatus']
                    for child_id in get_children_ids(cell)
                ]
                i = cell['RowIndex'] - 1
                j = cell['ColumnIndex'] - 1
                content[i][j] = ' '.join(cell_contents)

            # We assume that the first row corresponds to the column names
            dataframe = pd.DataFrame(content[1:], columns=content[0])
            dataframes.append(dataframe)
        for i, df in enumerate(dataframes):
            normal_range_col = None
            result_col = None
            
            # Find columns named 'normal range' and 'result'
            for col in df.columns:
                if col.lower() == 'normal range':
                    normal_range_col = col
                elif col.lower() == 'result':
                    result_col = col
                    
            # If normal range and result columns exist, create a new column named 'result within range'
            if normal_range_col and result_col:
                # Define a function to check if a result value is within the normal range
                def within_range(normal_range, result):
                
                    if isinstance(normal_range, str):
                        # Handle different types of normal range values
                        if normal_range.startswith('<'):
                            return float(result) < float(normal_range[1:])
                        elif normal_range.startswith('>'):
                            return float(result) > float(normal_range[1:])
                        elif normal_range.startswith('Up to'):
                            return float(result) <= float(normal_range[6:]) 
                        elif normal_range.startswith('less than'):
                            return float(result) < float(normal_range[10:])
                        elif normal_range.startswith('greater than'):
                            return float(result) > float(normal_range[13:])
                        else: 
                            return float(normal_range.split('-')[0]) <= float(result) <= float(normal_range.split('-')[1])
                df['result within range'] = df.apply(lambda row: 
                    within_range( row[normal_range_col], row[result_col]),axis=1)
                

                # Remove rows where 'result within range' is False
                df.drop(df[df['result within range']].index, inplace=True)
                df.drop(columns=['result within range'], inplace=True)
                print(df);
            with pd.ExcelWriter(f'data{i+1}_updated.xlsx') as writer:
                df.to_excel(writer, sheet_name=f'Table {i+1}', index=False)
        pdf = FPDF()
        for i in range(len(dataframes)):
            pdf.add_page()
            pdf.set_font("Arial", size=12)

            # Read the Excel file and add column names and data to the PDF
            excel_file = pd.read_excel(f'data{i+1}_updated.xlsx')
            columns = excel_file.columns.tolist()
            
            # Add column names as the first row
            pdf.set_fill_color(200, 200, 200)
            for col in columns:
                pdf.cell(40, 10, txt=col, border=1, fill=True, ln=False, align='C')
            pdf.ln()

            # Add data rows
            for _, row in excel_file.iterrows():
                for cell in row:
                    pdf.cell(40, 10, txt=str(cell), border=1, ln=False, align='C')
                pdf.ln()
        pdf.output("Updated.pdf")
        # Return the merged PDF file to the frontend
        return jsonify({'success': True, 'message': 'Analysis success.'})
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({'success': False, 'message': 'Analysis failed.'})
    
@app.route('/download')
def download():
    return send_file("Updated.pdf", as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)

