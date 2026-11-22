import codecs

with codecs.open('web/fund-houses.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()

# Find the JavaScript section
# Look for the search-related JavaScript
import re
# Find all script-like content
scripts = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)

for i, script in enumerate(scripts):
    lower = script.lower()
    if 'search' in lower or 'house' in lower or 'filter' in lower:
        print(f'Script {i} has search/filter related code')
        print(script[:300])
        print('---')
PYEOF