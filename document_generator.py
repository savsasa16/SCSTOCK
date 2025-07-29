# document_generator.py
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.colors import black, grey, lightgrey
import requests
from io import BytesIO

# เพิ่มฟอนต์ไทย (TH Sarabun New)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ตรวจสอบและลงทะเบียนฟอนต์หากยังไม่ได้ทำ
# ตรวจสอบให้แน่ใจว่าไฟล์ THSarabunNew.ttf และ THSarabunNew-Bold.ttf อยู่ใน directory เดียวกันกับไฟล์นี้
THAI_FONT_LOADED = False
try:
    pdfmetrics.registerFont(TTFont('Sarabun', 'THSarabunNew.ttf'))
    pdfmetrics.registerFont(TTFont('Sarabun-Bold', 'THSarabunNew-Bold.ttf'))
    THAI_FONT_LOADED = True
except Exception as e:
    print(f"Warning: THSarabunNew.ttf or THSarabunNew-Bold.ttf not found. Please ensure fonts are in the same directory or accessible path. Error: {e}")
    print("Falling back to Helvetica fonts. Thai characters will NOT display correctly.")

styles = getSampleStyleSheet()

# กำหนด FontName ที่จะใช้ตามว่าโหลดฟอนต์ไทยได้หรือไม่
if THAI_FONT_LOADED:
    normal_font = 'Sarabun'
    bold_font = 'Sarabun-Bold'
else:
    normal_font = 'Helvetica'
    bold_font = 'Helvetica-Bold'

# อัปเดตสไตล์ที่มีอยู่แล้ว และเพิ่มสไตล์ใหม่ที่จำเป็น
# ไม่ใช้ styles.add() สำหรับสไตล์ที่มีอยู่แล้วใน getSampleStyleSheet()

# อัปเดต TitleStyle (อันนี้เราสร้างเอง ไม่ได้มาจาก SampleStyleSheet)
styles.add(ParagraphStyle(name='TitleStyle', fontName=bold_font, fontSize=20, alignment=TA_CENTER, spaceAfter=14))

# อัปเดต Heading1 (มีอยู่แล้วใน SampleStyleSheet)
styles['Heading1'].fontName = bold_font
styles['Heading1'].fontSize = 14
styles['Heading1'].spaceAfter = 8
styles['Heading1'].alignment = TA_LEFT # เพิ่มการจัดตำแหน่งให้ชัดเจน

# อัปเดต Normal (มีอยู่แล้วใน SampleStyleSheet)
styles['Normal'].fontName = normal_font
styles['Normal'].fontSize = 12
styles['Normal'].spaceAfter = 6
styles['Normal'].alignment = TA_LEFT # เพิ่มการจัดตำแหน่งให้ชัดเจน

# เพิ่มสไตล์ใหม่ที่ไม่มีใน SampleStyleSheet
styles.add(ParagraphStyle(name='NormalRight', fontName=normal_font, fontSize=12, alignment=TA_RIGHT, spaceAfter=6))
styles.add(ParagraphStyle(name='NormalCenter', fontName=normal_font, fontSize=12, alignment=TA_CENTER, spaceAfter=6))
styles.add(ParagraphStyle(name='SmallText', fontName=normal_font, fontSize=10, spaceAfter=4))
styles.add(ParagraphStyle(name='BoldSmallText', fontName=bold_font, fontSize=10, spaceAfter=4))


def generate_document_pdf(doc_type, doc_data):
    # ... โค้ดส่วนที่เหลือเหมือนเดิมทั้งหมด ...
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    Story = []

    # Title
    title_text = "ใบรับสินค้า" if doc_type == "GR" else "ใบส่งสินค้า"
    Story.append(Paragraph(title_text, styles['TitleStyle']))
    Story.append(Spacer(1, 0.5*cm))

    # Header Info
    Story.append(Paragraph(f"<b>เลขที่เอกสาร:</b> {doc_data['document_number']}", styles['Normal']))
    Story.append(Paragraph(f"<b>วันที่:</b> {doc_data['document_date']}", styles['Normal']))
    
    if doc_type == "GR":
        Story.append(Paragraph(f"<b>จาก:</b> {doc_data.get('contact_name', '')}", styles['Normal']))
    else: # GI
        Story.append(Paragraph(f"<b>ถึง:</b> {doc_data.get('contact_name', '')}", styles['Normal']))
    
    Story.append(Spacer(1, 0.8*cm))

    # Items Table
    table_data = [['ลำดับ', 'รายการสินค้า', 'จำนวน', 'ราคาต่อหน่วย (ถ้ามี)', 'รวม (ถ้ามี)']]
    
    total_quantity_all_items = 0
    total_sum_all_items = 0
    
    for i, item in enumerate(doc_data['items']):
        item_unit_price = f"{item['unit_price']:,.2f}" if item.get('unit_price') is not None else '-'
        item_total = f"{item['total']:,.2f}" if item.get('total') is not None else '-'
        
        table_data.append([
            str(i + 1),
            Paragraph(item['name'], styles['Normal']),
            item['quantity'],
            item_unit_price,
            item_total
        ])
        total_quantity_all_items += item['quantity']
        if item.get('total') is not None:
            total_sum_all_items += item['total']

    # Add total row
    table_data.append([
        '',
        Paragraph("<b>รวม</b>", styles['NormalRight']),
        Paragraph(f"<b>{total_quantity_all_items}</b>", styles['NormalCenter']),
        '',
        Paragraph(f"<b>{total_sum_all_items:,.2f}</b>" if total_sum_all_items > 0 else '-', styles['NormalRight'])
    ])

    table = Table(table_data, colWidths=[1.5*cm, 7*cm, 2*cm, 3*cm, 3*cm])
    
    # กำหนดฟอนต์สำหรับสไตล์ตารางตามที่โหลดได้
    # ไม่ต้องมี if-else ซ้ำซ้อนที่นี่แล้ว เพราะ normal_font/bold_font ถูกกำหนดไว้แล้ว
    table_font_normal = normal_font
    table_font_bold = bold_font

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'), # Item name left align
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'), # Unit price right align
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'), # Total price right align
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), table_font_bold), # Header
        ('FONTNAME', (0, 1), (-1, -2), table_font_normal), # Data rows
        ('FONTNAME', (0, -1), (-1, -1), table_font_bold), # Total row
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, grey),
        ('BOX', (0, 0), (-1, -1), 1, black),
    ]))
    Story.append(table)
    Story.append(Spacer(1, 0.8*cm))

    # Notes
    if doc_data.get('notes'):
        Story.append(Paragraph(f"<b>หมายเหตุ:</b> {doc_data['notes']}", styles['Normal']))
        Story.append(Spacer(1, 0.5*cm))

    # Bill Image (if provided)
    if doc_data.get('bill_image_url'):
        try:
            response = requests.get(doc_data['bill_image_url'])
            if response.status_code == 200:
                img_data = BytesIO(response.content)
                img = Image(img_data)
                img._restrictSize(10*cm, 10*cm) # Limit image size
                Story.append(Paragraph("<b>รูปภาพอ้างอิง:</b>", styles['Normal']))
                Story.append(img)
                Story.append(Spacer(1, 0.5*cm))
            else:
                Story.append(Paragraph(f"<i>ไม่สามารถโหลดรูปภาพบิลได้: {response.status_code}</i>", styles['SmallText']))
        except requests.exceptions.RequestException as e:
            Story.append(Paragraph(f"<i>เกิดข้อผิดพลาดในการโหลดรูปภาพบิล: {e}</i>", styles['SmallText']))
        Story.append(Spacer(1, 0.5*cm))


    # Footer (Signatures)
    Story.append(Spacer(1, 1.5*cm))
    Story.append(Paragraph(f"ผู้จัดทำเอกสาร: {doc_data['issuer_name']}", styles['NormalRight']))
    Story.append(Paragraph("ลงชื่อ: ................................................", styles['NormalRight']))

    doc.build(Story)
    buffer.seek(0)
    return buffer