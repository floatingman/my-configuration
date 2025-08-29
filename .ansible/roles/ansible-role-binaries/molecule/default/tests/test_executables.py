import os
import stat
import json

def test_exist_binary(host):
    home = host.user("root").home
    data = json.loads(host.file("/tmp/ansible-role-binaries/binaries.txt").content_string)
    for bin in data:
        print("checking {}".format(bin['name']))
        filepath = os.path.join(home, ".local/bin", bin['name'])
        assert host.file(filepath).exists
        assert host.file(filepath).mode == 0o755
