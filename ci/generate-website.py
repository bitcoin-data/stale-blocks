import csv
import os

def HTML(table_body):
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Bitcoin Stale Block Dataset</title>
  <link rel="stylesheet" href="style.css" />
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB" crossorigin="anonymous">
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body class="container-fluid">
  <header class="row">
    <h1>Bitcoin Stale Block Dataset</h1>
    <p>Dataset of stale headers and blocks observed on the Bitcoin network.</p>
  </header>

  <section class="row">
    <h2>Chart</h2>
    <div id="chart" style="width: 100%; height: 400px;"></div>
  </section>

  <section class="row">
    <h2>Dataset contents</h2>
    <div class="table-container">
      <table id="data-table">
        <thead>
          <th>height</th>
          <th>hash</th>
          <th>header (hex)</th>
          <th>block (binary)</th>
        </thead>
        <tbody>{table_body}</tbody>
      </table>
    </div>
  </section>

  <footer>
  </footer>

  <script src="script.js"></script>
</body>
</html>
"""

def html_table_row(row):
    height = row[0]
    hash = row[1]
    header = row[2]
    header_code = f"<details><summary><code>{header[:16]}…</code></summary><code>{header}</code></details>"
    have_block = row[3]
    blockfile = f"blocks/{height}-{hash}.bin"
    blockfile_href = f"<a href='{blockfile}'>download</a>"
    missing = "<b style='color: red'>missing</b>"
    return f"""
      <tr>
        <td>{height}</td>
        <td><code>{hash}</code></td>
        <td>{header_code if header != "" else missing}</td>
        <td>{blockfile_href if have_block else missing}</span></td>
      </tr>
    """

def generate_table_rows():
    rows = []
    with open("stale-blocks.csv", "r") as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip header row

        for row in reader:
            height = row[0]
            hash = row[1]
            blockfile = f"blocks/{height}-{hash}.bin"
            row.append(os.path.exists(blockfile))
            rows.append(row)
    return rows

def main():
    rows = generate_table_rows()
    table_rows = "".join([html_table_row(row) for row in rows])
    print(table_rows)
    html = HTML(table_rows)

    with open("site/index.html", "w") as index:
        index.write(html)

if __name__ == "__main__":
    main()

 
