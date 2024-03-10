import PyPDF2

def read_pdf(file_path):
    with open(file_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        page = pdf_reader.pages[70]
        text = page.extract_text()
        print(text)

# get this pdf from https://charts.gc.ca/publications/tables-eng.html
pdf_text = read_pdf(r'D:\OneDrive\Documents\Water Activities\Mainland Diving\chs-shc-tct-tmc-vol6-2024-41208699.pdf')
print(pdf_text)
