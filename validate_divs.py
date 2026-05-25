import sys

def check_divs(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    depth = 0
    
    for i, line in enumerate(lines):
        line_num = i + 1
        opens = line.count('<div')
        closes = line.count('</div')
        if opens > 0 or closes > 0:
            depth += opens
            depth -= closes
            if line_num >= 460 and line_num <= 480:
                print(f"{line_num:4} [depth={depth:2}] {line.strip()}")
                
check_divs("d:\\Documents\\Kerjaan\\MotorizeAntenna\\code\\templates\\index.html")
