import os

files = [
    'web/about.html', 'web/docs.html', 'web/explorer.html',
    'web/fund-house.html', 'web/fund-houses.html', 'web/index.html',
    'web/privacy.html', 'web/terms.html', 'web/schemes.html',
    'web/categories.html', 'web/status.html', 'web/404.html',
    'web/data-sources.html'
]

for f in files:
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        
        # Replace data-swagger button labels: Swagger UI -> API reference
        # The button has data-swagger attribute and shows "Swagger UI"
        old_btn = 'data-swagger href="/api/docs">Swagger UI'
        new_btn = 'data-swagger href="/api/docs">API reference'
        content = content.replace(old_btn, new_btn)
        
        old_btn2 = 'data-swagger href="docs.html">Swagger UI'
        new_btn2 = 'data-swagger href="docs.html">API reference'
        content = content.replace(old_btn2, new_btn2)
        
        # Replace plain text "Swagger UI" with "API reference"
        content = content.replace('Swagger UI', 'API reference')
        
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(content)
        print('Updated: ' + f)

print('Done')