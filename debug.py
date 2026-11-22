import codecs

with codecs.open('web/schemes.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()
checks = {
    'searchInput defined': 'const searchInput' in content,
    'fundHouseSelect defined': 'const fundHouseSelect' in content,
    'categorySelect defined': 'const categorySelect' in content,
    'debouncedLoad function': 'function debouncedLoad' in content,
    'searchInput.addEventListener': 'searchInput.addEventListener' in content,
    'fundHouseSelect.addEventListener': 'fundHouseSelect.addEventListener' in content,
    'categorySelect.addEventListener': 'categorySelect.addEventListener' in content,
    'loadSchemes(0) called': 'loadSchemes(0)' in content,
}
for check, result in checks.items():
    print(f'{check}: {"OK" if result else "MISSING"}')