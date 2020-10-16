# PKG-MANAGER

### Generate `qubes-builder` example config file based on `components.json`

Example:
```
./pkg-manager.py --release 4.0 --generate-conf ../example-configs/qubes-os-r4.0.conf --components-file components.json
```

### Create/Update packages list for the provided component.

Create/Update packages list in its corresponding file into `components/` then update the whole `components.json`.

Example:
```
./pkg-manager.py --release 4.0 --generate-pkg-list core-agent-linux --components-file components.json --qubes-src /home/user/qubes-builder-4.0/qubes-src/
```

> Note: `all` keyword is accepted for regenerating packages list for all components.