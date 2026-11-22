import os

files = [
    'web/about.html', 'web/docs.html', 'web/explorer.html',
    'web/fund-house.html', 'web/fund-houses.html', 'web/index.html',
    'web/privacy.html', 'web/terms.html', 'web/schemes.html',
    'web/categories.html', 'web/status.html'
]

for f in files:
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        
        # 1. Replace data-swagger links: Swagger UI -> API reference
        content = content.replace('data-swagger href="docs.html">Swagger UI', 'data-swagger href="docs.html">API reference')
        
        # 2. Replace text mentions: Swagger UI -> API reference
        content = content.replace('Swagger UI', 'API reference')
        
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(content)
        print('Updated: ' + f)

print('Done')