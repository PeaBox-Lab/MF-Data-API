with open('web/schemes.html', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.read().split('\n')
for i in range(330, 350):
    if i < len(lines):
        print(f'{i+1}: {lines[i]}')
"