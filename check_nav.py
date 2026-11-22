import os, re

files = [
    'web/about.html', 'web/docs.html', 'web/explorer.html',
    'web/fund-house.html', 'web/fund-houses.html', 'web/index.html',
    'web/privacy.html', 'web/terms.html', 'web/schemes.html',
    'web/categories.html', 'web/status.html', 'web/404.html'
]

for f in files:
    if os.path.exists(f):
        with open(f, 'r') as fh:
            content = fh.read()
        m = re.search(r'<nav class="nav-links"[^>]*>.*?</nav>', content, re.DOTALL)
        if m:
            nav = m.group()
            checks = {
                'Funds': 'Fund' in nav,
                'Schemes': 'Schemes' in nav,
                'Fund Houses': 'Fund Houses' in nav,
                'Categories': 'Categories' in nav,
                'Swagger': 'Swagger' in nav,
                'API ref': 'API reference' in nav,
            }
            all_ok = all(checks.values())
            print(f + ': ' + str(checks) + ' | ok=' + str(all_ok))