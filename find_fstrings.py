import re
with open("backend_orangepi.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if re.search(r'\bf[\'"]', line):
            print(f"{i+1}: {line.strip()}")
