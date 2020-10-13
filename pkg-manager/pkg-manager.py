#!/usr/bin/python3

import argparse
import os
import sys
import json
import subprocess
import tempfile

from jinja2 import Template

DEBIAN = {
    "stretch": "debian-9",
    "buster": "debian-10",
    "bullseye": "debian-11"
}


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        default="4.1"
    )
    parser.add_argument(
        "--generate-components",
        required=False,
        action="store_true"
    )
    parser.add_argument(
        "--generate-conf",
        required=False,
        help="Destination file for generating qubes-builder configuration file."
    )
    parser.add_argument(
        "--generate-pkg-list",
        required=False,
        nargs='+',
        help="Generate packages list for each distro per component."
             "For processing all components use value 'all'."
    )
    parser.add_argument(
        "--qubes-src",
        required=False,
        help="Local path of Qubes sources corresponding to requested release"
    )
    parser.add_argument(
        "--components-file",
        required=False,
        help="Input components list ('components.json')"
    )
    return parser.parse_args()


def get_makefile_value(makefile, var, env=None):
    # Very simple implementation of getting makefile variables values
    value = ''
    if os.path.exists(os.path.dirname(makefile)):
        curr_dir = os.path.dirname(makefile)
        with tempfile.NamedTemporaryFile(dir=curr_dir) as fd:
            content = """
            ORIG_SRC ?= {orig_src}
            include {orig_src}/../mgmt-salt/Makefile.builder
            include {makefile}
            
            print-%  : ; @echo $($*)
            """.format(orig_src=os.path.dirname(makefile), makefile=makefile)
            fd.write(content.encode('utf-8'))
            fd.seek(0)
            cmd = "make -f %s print-%s" % (fd.name, var)
            output = subprocess.check_output(
                [cmd], cwd=curr_dir, shell=True, text=True, env=env)
            value = output.rstrip('\n')

    return value


def get_rpm_packages_list(specin):
    rpm_packages_list = []
    # in case of still non existent .spec.in
    if not os.path.exists(specin):
        spec = specin.rstrip('.in')
        if not os.path.exists(spec):
            return rpm_packages_list
        specin = spec

    with open(specin) as fd_in:
        content = fd_in.read()
    curr_dir = os.path.dirname(specin)
    with tempfile.NamedTemporaryFile(dir=curr_dir) as fd_spec:
        # WIP
        content = content.replace('@VERSION@', '1.0.0')
        content = content.replace('@VERSION1@', '1.0.0')
        content = content.replace('@REL@', '1')
        content = content.replace('@CHANGELOG@', '')
        content = content.replace('@BACKEND_VMM@', 'xen')
        fd_spec.write(content.encode('utf-8'))
        fd_spec.seek(0)
        spec = fd_spec.name
        if os.environ.get('DEBUG') == 1:
            cmd = "/usr/bin/rpmspec -q --qf '%{name}\n' " + spec + " 2>/dev/null"
        else:
            cmd = "/usr/bin/rpmspec -q --qf '%{name}\n' " + spec
        output = subprocess.check_output([cmd], cwd=curr_dir, shell=True, text=True).rstrip('\n')
        rpm_packages_list = output.split('\n')
    return rpm_packages_list


def get_rpm_spec_files(component_path, dom0=None, vm=None):
    makefile_path = os.path.join(component_path, 'Makefile.builder')
    env = None
    if dom0:
        env = {'PACKAGE_SET': 'dom0', 'DIST': dom0}
    if vm:
        env = {'PACKAGE_SET': 'vm', 'DIST': vm}

    specs = get_makefile_value(makefile_path, 'RPM_SPEC_FILES', env)
    return specs.split()


def get_deb_packages_list(control):
    deb_packages_list = []
    with open(control) as fd:
        output = fd.read().split('\n')
        for line in output:
            if line.startswith('Package: '):
                if 'arm64' in line or 'armhf' in line:
                    continue
                deb_packages_list.append(line.replace('Package: ', ''))
    return deb_packages_list


def get_deb_control_file(component_path, vm):
    makefile_path = os.path.join(component_path, 'Makefile.builder')
    env = os.environ.copy()
    env.update({'PACKAGE_SET': 'vm', 'DISTRIBUTION': 'debian', 'DIST': vm})
    debian_build_dirs = get_makefile_value(makefile_path, 'DEBIAN_BUILD_DIRS', env)
    control = None
    if debian_build_dirs:
        control = os.path.join(debian_build_dirs, 'control')
    return control


class PkgCli:
    def __init__(self, release):
        self.release = release

        self.data = {}
        self.builder_plugins = []
        self.windows_components = []
        self.filtered_components = []

        self.qubes_src = ''
        self.components_file = ''

    def is_devel_version(self):
        return self.data["releases"][self.release].get("devel", 0)

    def get_dom0(self):
        return self.data["releases"][self.release]["dom0"]

    def get_vms(self):
        return self.data["releases"][self.release]["vms"]

    def get_components(self):
        components = []
        for key, val in self.data["components"].items():
            if val["releases"].get(self.release):
                components.append(key)

        return components

    def get_branch(self, component):
        return self.data["components"][component]["releases"][self.release][
            "branch"]

    def get_branches(self):
        branches = []
        for component in self.get_components():
            branch = self.get_branch(component)
            if branch != "release%s" % self.release:
                if branch == "master" and self.is_devel_version() == 1:
                    continue
                branches.append(
                    'BRANCH_%s = %s' % (component.replace('-', '_'), branch))

        return branches

    def get_packages_list(self, component, dom0=None, vm=None):
        packages_list = []
        if self.qubes_src:
            component_path = os.path.join(self.qubes_src, component)
            if dom0 or vm.startswith('fc') or vm.startswith('centos'):
                specs = get_rpm_spec_files(component_path, dom0, vm)
                specins = [os.path.join(component_path, spec + '.in')
                           for spec in specs]
                for specin in specins:
                    packages_list += get_rpm_packages_list(specin)
            if vm and DEBIAN.get(vm, None):
                control = get_deb_control_file(component_path, vm)
                if control:
                    control = os.path.join(component_path, control)
                    packages_list += get_deb_packages_list(control)

        return packages_list

    def parse_components(self):
        for component in self.get_components():
            if self.data["components"][component].get("plugin", None) == 1:
                self.builder_plugins.append(component)
            if 'windows' in component:
                self.windows_components.append(component)

            if component not in self.builder_plugins + self.windows_components:
                self.filtered_components.append(component)

    def generate_template_labels(self):
        template_labels = []
        for dist in self.data["releases"][self.release]["vms"]:
            label_dist = None
            if dist.startswith("fc"):
                label_dist = dist.replace("fc", "fedora-")
            elif dist.startswith("centos"):
                label_dist = dist.replace("centos", "centos-")
            elif DEBIAN.get(dist, None):
                label_dist = DEBIAN[dist]

            if label_dist:
                template_labels += [
                    "%s:%s" % (dist, label_dist),
                    "%s+minimal:%s-minimal" % (dist, label_dist),
                    "%s+xfce:%s-xfce" % (dist, label_dist)
                ]

        template_labels.append(
            "buster+whonix-gateway+minimal+no-recommends:whonix-gw-15")

        return template_labels

    def generate_template_alias(self):
        template_aliases = []
        for dist in self.data["releases"][self.release]["vms"]:
            if DEBIAN.get(dist, None):
                template_aliases += [
                    "%s:%s+standard" % (dist, dist),
                    "%s+gnome:%s+gnome+standard" % (dist, dist),
                    "%s+minimal:%s+minimal+no-recommends" % (dist, dist)
                ]

        template_aliases += [
            "whonix-gateway-15:buster+whonix-gateway+minimal+no-recommends",
            "whonix-workstation-15:buster+whonix-workstation+minimal+no-recommends"
        ]

        return template_aliases

    def generate_conf(self, conf_file):
        with open('template.conf.jinja', 'r') as template_fd:
            template = Template(template_fd.read())

        self.parse_components()

        conf = {
            "devel": self.is_devel_version(),
            "release": self.release,
            "dist_dom0": self.get_dom0(),
            "dists_vm": self.get_vms(),
            "builder_plugins": self.builder_plugins,
            "windows_components": self.windows_components,
            "components": self.filtered_components,
            "template_labels": self.generate_template_labels(),
            "template_aliases": self.generate_template_alias(),
            "branches": self.get_branches()
        }

        generated_conf = template.render(**conf)
        with open(conf_file, 'w') as fd:
            fd.write(generated_conf)

    def generate_packages_list(self, components):
        if 'all' in components:
            components = self.get_components()
        else:
            components = set(components).intersection(
                set(self.get_components()))
        for component in components:
            if component == 'linux-template-builder':
                continue
            with open('components/%s.json' % component) as fd:
                data_component = json.loads(fd.read())

            list_dom0 = self.get_packages_list(component, dom0=self.get_dom0())
            data_component[component]["releases"][self.release]["dom0"] = {}
            data_component[component]["releases"][self.release]["dom0"][self.get_dom0()] = list_dom0

            data_component[component]["releases"][self.release]["vms"] = {}
            for vm in self.get_vms():
                list_vm = self.get_packages_list(component, vm=vm)
                if list_vm:
                    data_component[component]["releases"][self.release]["vms"][vm] = list_vm

            with open('components/%s.json' % component, 'w') as fd:
                fd.write(json.dumps(data_component, indent=4))

    def load_components(self):
        with open(self.components_file) as fd:
            self.data = json.loads(fd.read())

    # skeleton_components.json + components/*.json -> components.json
    def generate_components(self):
        with open('skeleton_components.json') as fd:
            data = json.loads(fd.read())

        for component in data["components"]:
            with open('components/%s.json' % component) as fd:
                data_component = json.loads(fd.read())
                data["components"][component] = data_component[component]

        with open(self.components_file, 'w') as fd:
            fd.write(json.dumps(data, indent=4))

    # skeleton_components.json -> component/*.json
    # this method is not called: it is used for init of assets where manual
    # adjustments are needed for example in branches for vmm-xen or linux-kernel
    def generate_assets(self):
        with open('skeleton_components.json') as fd:
            data = json.loads(fd.read())
        for component in data["components"]:
            with open('components/%s.json' % component, 'w') as fd:
                content = {
                    component: data["components"][component]
                }
                fd.write(json.dumps(content, indent=4))

    ## WIP: replace abose function: only specify particular branche like app-*
    ## linux-kernel or vmm-xen.
    # # skeleton_components.json -> component/*.json
    # # this method is not called: it is used for init of assets where manual
    # # adjustments are needed for example in branches for vmm-xen or linux-kernel
    # def generate_assets(self):
    #     with open('skeleton_components.json') as fd:
    #         data = json.loads(fd.read())
    #
    #     for component in data["components"]:
    #         with open('components/%s.json' % component, 'w') as fd:
    #             content = data["components"][component]
    #             content["releases"] = {}
    #             for release in data["releases"].keys():
    #                 if data["releases"][release].get('devel', 0) == 1:
    #                     branch = 'master'
    #                 else:
    #                     branch = 'release%s' % release
    #                 content["releases"][release] = {
    #                         "branch": branch
    #                     }
    #
    #             output = {
    #                 component: content
    #             }
    #             fd.write(json.dumps(output, indent=4))


def main():
    args = get_args()
    cli = PkgCli(args.release)

    if not args.components_file:
        print("ERROR: Please provide 'components.json' location/destination")
        return 1

    cli.components_file = os.path.abspath(args.components_file)
    if args.generate_components:
        # generate components.json from skeleton_components.json
        cli.generate_components()
    elif args.generate_pkg_list:
        if not args.qubes_src:
            print("ERROR: Please provide 'qubes-src' location")
            return 1
        cli.qubes_src = os.path.abspath(args.qubes_src)
        cli.load_components()
        # update components/* assets
        cli.generate_packages_list(args.generate_pkg_list)

        # update components.json
        cli.generate_components()
    elif args.generate_conf:
        cli.load_components()
        cli.generate_conf(args.generate_conf)


if __name__ == "__main__":
    sys.exit(main())
