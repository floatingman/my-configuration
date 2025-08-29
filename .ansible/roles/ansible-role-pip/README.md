# ansible-role-pip

Install packages via python's pip as user.

## Test

Run `molecule test` to test this role in a docker container

## Requirements

- `pip` is available in your $PATH

## Role Variables

- `pip_packages`: a list of all pip packages to be installed

## Dependencies

- NA

## Example Playbook

See [converge.yml](https://github.com/Allaman/ansible-role-pip/blob/main/molecule/default/converge.yml)

## License

MIT
