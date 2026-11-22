with open('web/schemes.html', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find the position to insert the divs - after the search-hint paragraph and before the table-wrap
search_hint_pos = content.find('class="search-hint"')
table_wrap_pos = content.find('class="table-wrap"')

if search_hint_pos == -1 or table_wrap_pos == -1:
    print('Could not find required divs')
    exit(1)

# The new divs to insert
new_divs = '''

<div id="search-results" class="search-results">
  <div class="search-empty" style="display:none;">No schemes matched that search.</div>
</div>

'''

# Insert the divs before the table-wrap
new_content = content[:table_wrap_pos] + new_divs + content[table_wrap_pos:]

with open('web/schemes.html', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Added search-results and search-empty divs')