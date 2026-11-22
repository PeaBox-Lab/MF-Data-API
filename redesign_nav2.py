import os
import re

# The new complete navigation HTML for each file
# This replaces the entire <nav> section

new_nav_structure = '''      <nav class="nav-links" id="site-nav" aria-label="Main navigation">
        <a href="index.html">Home</a>
        
        <div class="dropdown">
          <a href="docs.html">API reference ▼</a>
          <div class="dropdown-content">
            <a href="docs.html">API reference</a>
            <a href="docs.html#static-mode">Static JSON</a>
            <a href="docs.html#updates">Update schedule</a>
            <a href="docs.html#license">License & attribution</a>
          </div>
        </div>
        
        <div class="dropdown">
          <a href="#">Funds ▼</a>
          <div class="dropdown-content">
            <a href="schemes.html">Schemes</a>
            <a href="fund-houses.html">Fund Houses</a>
            <a href="categories.html">Categories</a>
          </div>
        </div>
        
        <a href="explorer.html">Explorer</a>
        
        <a href="status.html">Status</a>
        <a href="data-sources.html">Data Sources</a>
      </nav>'''

# The old nav structure to find and replace
old_nav_marker = '''      <nav class="nav-links" id="site-nav" aria-label="Main navigation">'''

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
        
        # Find and replace the entire nav section
        # Find the opening nav tag and the closing </nav> tag
        start_marker = '      <nav class="nav-links" id="site-nav"'
        start_pos = content.find(start_marker)
        
        if start_pos != -1:
            # Find the closing </nav> tag
            end_pos = content.find('</nav>', start_pos)
            if end_pos != -1:
                # Replace the entire nav section
                new_content = content[:start_pos] + new_nav_structure + content[end_pos+6:]
                
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(new_content)
                print('Updated: ' + f)
            else:
                print('No </nav> found: ' + f)
        else:
            print('No nav marker found: ' + f)