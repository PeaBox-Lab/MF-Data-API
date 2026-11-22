import codecs

with codecs.open('web/fund-houses.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()

# Check for the search input and event listener
print('house-search exists:', 'id="house-search"' in content)
print('house-search addEventListener:', 'house-search.addEventListener' in content)

# Find the relevant lines
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if 'house-search' in line.lower() or 'debouncedFilter' in line.lower() or 'addEventListener' in line.lower():
        print(f'Line {i}: {line[:100]}')