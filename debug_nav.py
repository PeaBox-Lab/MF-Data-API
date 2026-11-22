import codecs

with codecs.open('web/schemes.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()
lines = content.split('\n')
# Print lines 329-355
for i in range(328, min(355, len(lines))):
    print(f'{i+1}: {lines[i]}')
PYEOF