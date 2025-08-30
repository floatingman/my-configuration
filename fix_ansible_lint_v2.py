#!/usr/bin/env python3

import re
import sys

def fix_fqcn(content):
    """Replace builtin modules with their FQCN equivalents"""
    # Use regex to match module names more precisely
    patterns = {
        r'\bfile:': 'ansible.builtin.file:',
        r'\btemplate:': 'ansible.builtin.template:',
        r'\bstat:': 'ansible.builtin.stat:',
        r'\bcommand:': 'ansible.builtin.command:',
        r'\bfail:': 'ansible.builtin.fail:',
        r'\bdebug:': 'ansible.builtin.debug:',
        r'\bunarchive:': 'ansible.builtin.unarchive:',
        r'\bcopy:': 'ansible.builtin.copy:',
        r'\bshell:': 'ansible.builtin.shell:',
        r'\bsystemd:': 'ansible.builtin.systemd:',
        r'\bwait_for:': 'ansible.builtin.wait_for:',
        r'\bslurp:': 'ansible.builtin.slurp:',
        r'\bset_fact:': 'ansible.builtin.set_fact:',
        r'\bpause:': 'ansible.builtin.pause:',
        r'\bfetch:': 'ansible.builtin.fetch:',
        r'\bget_url:': 'ansible.builtin.get_url:',
        r'\binclude_role:': 'ansible.builtin.include_role:',
        r'\blineinfile:': 'ansible.builtin.lineinfile:',
        r'\buser:': 'ansible.builtin.user:',
        r'\bgroup:': 'ansible.builtin.group:',
        r'\bservice:': 'ansible.builtin.service:',
        r'\bpackage:': 'ansible.builtin.package'
    }

    # First, fix any existing incorrect patterns
    content = re.sub(r'ansible\.builtin\.ansible\.builtin\.', 'ansible.builtin.', content)
    content = re.sub(r'lineinansible\.builtin\.file:', 'ansible.builtin.lineinfile:', content)
    content = re.sub(r'ansible\.builtin\.lineinansible\.builtin\.file:', 'ansible.builtin.lineinfile:', content)
    content = re.sub(r'become_ansible\.builtin\.user:', 'become_user:', content)
    content = re.sub(r'ansible\.builtin\.group:', 'group:', content)

    # Only apply replacements if not already FQCN
    for pattern, replacement in patterns.items():
        # Don't replace if already has ansible.builtin prefix
        content = re.sub(f'(?<!ansible\.builtin\.){pattern}', replacement, content)

    return content

def fix_truthy_values(content):
    """Fix truthy values"""
    # Replace 'yes' with true and 'no' with false
    content = re.sub(r':\s*yes$', ': true', content, flags=re.MULTILINE)
    content = re.sub(r':\s*no$', ': false', content, flags=re.MULTILINE)
    return content

def fix_trailing_spaces(content):
    """Remove trailing spaces"""
    lines = content.split('\n')
    fixed_lines = [line.rstrip() for line in lines]
    return '\n'.join(fixed_lines)

def main():
    if len(sys.argv) != 2:
        print("Usage: fix_ansible_lint_v2.py <file>")
        sys.exit(1)

    filename = sys.argv[1]

    with open(filename, 'r') as f:
        content = f.read()

    # Apply fixes
    content = fix_fqcn(content)
    content = fix_truthy_values(content)
    content = fix_trailing_spaces(content)

    with open(filename, 'w') as f:
        f.write(content)

    print(f"Fixed {filename}")

if __name__ == '__main__':
    main()
