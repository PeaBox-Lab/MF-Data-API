import codecs

with codecs.open('web/categories.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read().lower()

checks = {
    'Has category filter': 'category' in content,
    'Has fund house filter': 'fund house' in content,
}
for check, result in checks.items():
    print(f'{check}: {"OK" if result else "MISSING"}')