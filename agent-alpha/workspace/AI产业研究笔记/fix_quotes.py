import re
with open('workspace/AI产业研究笔记/generate_docx.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Pattern: CJK_CHAR + "text"CJK_CHAR where "text" is a Chinese quotation
pattern = re.compile(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])"([^"]{1,30}?)"([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])')

def replacer(m):
    return m.group(1) + '\\u201C' + m.group(2) + '\\u201D' + m.group(3)

text = pattern.sub(replacer, text)

with open('workspace/AI产业研究笔记/generate_docx.js', 'w', encoding='utf-8') as f:
    f.write(text)
print('Fixed all Chinese quotes')
