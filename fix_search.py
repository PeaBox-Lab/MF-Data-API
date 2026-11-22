import codecs

with codecs.open('web/schemes.html', 'r', 'utf-8', errors='replace') as f:
    content = f.read()

# Add the search-results and search-empty divs after the search-hint paragraph
# The search-hint paragraph ends with: "Press Enter or click Search. Results update the table below."
# We need to insert the divs after the .search-hint paragraph and before the .table-wrap div

# Find the position to insert
search_hint_pos = content.find('class="search-hint"')
if search_hint_pos == -1:
    print('Could not find search-hint div')
    exit(1)

# Find the table wrap position
table_wrap_pos = content.find('class="table-wrap"')
if table_wrap_pos == -1:
    print('Could not find table-wrap div')
    exit(1)

# The new divs to insert
new_divs = '''

<div id="search-results" class="search-results">
  <div class="search-empty" style="display:none;">No schemes matched that search.</div>
</div>

'''

# Insert the divs after the search-hint paragraph
new_content = content[:table_wrap_pos] + new_divs + content[table_wrap_pos:]

with codecs.open('web/schemes.html', 'w', 'utf-8') as f:
    f.write(new_content)
print('Added search-results and search-empty divs')
"