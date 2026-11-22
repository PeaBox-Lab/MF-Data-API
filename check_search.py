with open('web/schemes.html', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()
checks = {
    'search-shell div exists': 'search-shell' in content,
    'search-results div exists': 'search-results' in content,
    'search-empty div exists': 'search-empty' in content,
}
for check, result in checks.items():
    print(f'{check}: {"OK" if result else "MISSING"}')