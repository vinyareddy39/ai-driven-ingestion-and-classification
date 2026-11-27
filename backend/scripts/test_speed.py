import cv2, pytesseract, fitz, numpy as np, time
pytesseract.pytesseract.tesseract_cmd = r'C:\ml\tools\tesseract_ub\tesseract.exe'
doc = fitz.open('data/dataset/val/invoice_0121.pdf')
pix = doc[0].get_pixmap(dpi=300)
img = cv2.cvtColor(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n), cv2.COLOR_RGBA2GRAY)

t0 = time.time()
data = pytesseract.image_to_data(img, config='--psm 4', output_type=pytesseract.Output.DICT)
lines = {}
for i in range(len(data['text'])):
    w = data['text'][i].strip()
    if w:
        k = (data['block_num'][i], data['line_num'][i])
        lines.setdefault(k, []).append(w)
full = '\n'.join(' '.join(v) for v in lines.values())
print(f"Done in {time.time()-t0:.2f}s! Extracted chars: {len(full)}")
print("Snippet:\n", full[:200])
