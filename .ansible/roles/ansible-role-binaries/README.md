# ansible-role-binaries

Installs several applications via downloading and placing the executable in PATH on Linux based systems. Does **not** install the package via package manager. Please be aware that this comes with disadvantages, too.

Why not [eget](https://github.com/zyedidia/eget)?

Although I think this is an awesome project I prefer to define my setup in a more declarative way and additionally Ansible gives me also more flexibility.

## Test

Run `molecule test` to test this role via docker

## Requirements

## Role Variables

- `binaries`: this is the data structure that defines packages to install.
  - `binaries.name`: The name of the binary to be placed in the path
  - `binaries.url`: The download URL of the application
  - `binaries.extract`: `True` only if the download is an archive
  - `binaries.bin_name`: The name of the binary if not the same as `bin.name`
  - `binaries.bin_path`: The path of the binary e.g. after extraction (only the folder not the binary itself)
- `is_test`: Only required and set to `True` in molecule tests

## Dependencies

## Example Playbook

See [converge.yml](https://github.com/Allaman/ansible-role-binaries/blob/master/molecule/default/converge.yml) which is used for testing

## License

MIT
