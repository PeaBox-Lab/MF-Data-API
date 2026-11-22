import codecs

with codecs.open('web/schemes.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()

# Find and print the debouncedLoad function and surrounding code
import re
# Find debouncedLoad
match = re.search(r'function debouncedLoad\([^)]*\)\{[^}]*\}', content, re.DOTALL)
if match:
    print('debouncedLoad function:')
    print(match.group())
    print('---')

# Find the event listener attachments
match2 = re.search(r'searchInput\.addEventListener[^;]*;', content, re.DOTALL)
if match2:
    print('searchInput.addEventListener:')
    print(match2.group())
    print('---')

match3 = re.findall(r'fundHouseSelect\.addEventListener[^;]*;', content, re.DOTALL)
if match3:
    print('fundHouseSelect.addEventListener:')
    for m in match3:
        print(m)
    print('---')

match4 = re.findall(r'categorySelect\.addEventListener[^;]*;', content, re.DOTALL)
if match4:
    print('categorySelect.addEventListener:')
    for m in match4:
        print(m)
    print('---')
PYEOF