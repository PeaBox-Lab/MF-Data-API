import os
import re

# The new complete navigation HTML structure
# This replaces the entire <nav> section
new_nav_structure = '''      <nav class="nav-links" id="site-nav" aria-label="Main navigation">
        <a href="#features">Features</a>
        <a href="docs.html">Documentation</a>
        <a href="explorer.html">Explorer</a>
        
        <div class="dropdown">
          <a href="#">Fund Houses ▼</a>
          <div class="dropdown-content">
            <a href="schemes.html">Schemes</a>
            <a href="categories.html">Categories</a>
          </div>
        </div>
        
        <a href="status.html">Status</a>
        <a href="data-sources.html">Sources</a>
      </nav>'''

# The old nav marker to find and replace
old_nav_marker = '      <nav class="nav-links" id="site-nav" aria-label="Main navigation">'

files = [
    'web/about.html', 'web/docs.html', 'web/explorer.html',
    'web/fund-house.html', 'web/fund-houses.html', 'web/index.html',
    'web/privacy.html', 'web/terms.html', 'web/schemes.html',
    'web/categories.html', 'web/status.html', 'web/404.html',
    'web/data-sources.html'
]

updated = []
for f in files:
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        
        start_pos = content.find(old_nav_marker)
        if start_pos != -1:
            end_pos = content.find('</nav>', start_pos)
            if end_pos != -1:
                new_content = content[:start_pos] + new_nav_structure + content[end_pos+6:]
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(new_content)
                updated.append(f)
                print('Updated: ' + f)
            else:
                print('No </nav> found: ' + f)
        else:
            print('No marker found: ' + f)

print()
print('Updated ' + str(len(updated)) + ' files')