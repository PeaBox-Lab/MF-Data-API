import os, re, json

# The new navigation structure
# Replace the 8 standalone nav links with:
# - Home
# - Docs (dropdown with API reference, Static JSON, etc.)
# - Funds (dropdown with Schemes, Fund Houses, Categories)
# - Status
# - Data Sources

# New dropdown HTML for "Funds"
funds_dropdown = '''      <div class="dropdown">
          <a href="#">Funds ▼</a>
          <div class="dropdown-content">
            <a href="schemes.html">Schemes</a>
            <a href="fund-houses.html">Fund Houses</a>
            <a href="categories.html">Categories</a>
          </div>
        </div>'''

# New dropdown HTML for "Docs"
docs_dropdown = '''      <div class="dropdown">
          <a href="docs.html">API reference ▼</a>
          <div class="dropdown-content">
            <a href="docs.html">API reference</a>
            <a href="docs.html#static-mode">Static JSON</a>
            <a href="docs.html#updates">Update schedule</a>
            <a href="docs.html#license">License & attribution</a>
          </div>
        </div>'''

# Standard nav without dropdowns (for pages that keep it simple)
standard_nav = '''      <nav class="nav-links" id="site-nav" aria-label="Main navigation">
        <a href="index.html">Home</a>
        
''' + funds_dropdown + '''\

        ''' + docs_dropdown + '''\

        <a href="status.html">Status</a>
        <a href="data-sources.html">Data Sources</a>
      </nav>'''

# Replace the nav in each file
files = [
    'web/about.html', 'web/docs.html', 'web/explorer.html',
    'web/fund-house.html', 'web/fund-houses.html', 'web/index.html',
    'web/privacy.html', 'web/terms.html', 'web/schemes.html',
    'web/categories.html', 'web/status.html', 'web/404.html'
]

for f in files:
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        
        # Replace the nav section
        old_marker = '      <nav class="nav-links" id="site-nav" aria-label="Main navigation">'
        if old_marker in content:
            new_content = content.replace(old_marker, standard_nav)
            if new_content != content:
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(new_content)
                print('Updated: ' + f)
            else:
                print('No change: ' + f)
        else:
            print('Marker not found: ' + f)