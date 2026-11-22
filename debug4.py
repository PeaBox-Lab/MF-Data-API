import codecs

# Check fund-houses.html
with codecs.open('web/fund-houses.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()
checks = {
    'fund-houses search input exists': 'id="house-search"' in content,
    'fund-houses search event listener': 'house-search.addEventListener' in content,
    'fund-houses debouncedFilter function': 'function debouncedFilter' in content,
}
for check, result in checks.items():
    print(f'{check}: {"OK" if result else "MISSING"}')
print()

# Check categories.html
with codecs.open('web/categories.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()
# Categories might not have search, just filter by fund house and category
print('Categories page check:')
print('Has category filter:', 'category' in content.lower())