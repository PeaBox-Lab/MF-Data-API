import codecs

with codecs.open('web/schemes.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()

# Check for the input elements
checks = {
    'scheme-search input exists': 'id="scheme-search"' in content,
    'fund-house-filter exists': 'id="fund-house-filter"' in content,
    'category-filter exists': 'id="category-filter"' in content,
    'searchInput variable has element': 'document.querySelector' in content or '$(\"#scheme-search\")' in content,
}
for check, result in checks.items():
    print(f'{check}: {"OK" if result else "MISSING"}')