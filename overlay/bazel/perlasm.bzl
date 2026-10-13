"""Run OpenSSL's perlasm scripts to produce assembly for one flavour.

Every perlasm script is wrapped in a perl_binary (see openssl_perlasm_scripts) and
run as its own action, for per-file caching and full parallelism. Like the
overlay's other build-time Perl tools (batch_dofile, progs_gen, mkbuildinf),
those binaries are built for the execution platform; this rule resolves no
Perl toolchain of its own. The one toolchain it does resolve is the C++
toolchain, because the scripts probe the *target* compiler ($CC) to decide
which instruction-set paths to emit.
"""

load("@rules_cc//cc:action_names.bzl", "ACTION_NAMES")
load("@rules_cc//cc:defs.bzl", "CcInfo", "cc_common")
load("@rules_cc//cc:find_cc_toolchain.bzl", "CC_TOOLCHAIN_TYPE", "use_cc_toolchain")
load("@rules_perl//perl:perl.bzl", "perl_binary")

# The perlasm tools and the C++ toolchain whose compiler they probe must be
# resolved for the same execution platform, so both live in one exec group.
_EXEC_GROUP = "perlasm"

def openssl_perlasm_tool_name(script):
    """Name of the perl_binary wrapping a perlasm script (e.g. "perlasm/crypto/aes/asm/aesni-x86_64.pl")."""
    return "perlasm/" + script

def openssl_perlasm_tools(scripts_to_outs):
    """Turn a {script path: output path} dict from parse_perlasm_gen into {perl_binary label: output path}."""
    return {":" + openssl_perlasm_tool_name(script): out for script, out in scripts_to_outs.items()}

def openssl_perlasm_scripts(name, scripts, data, **kwargs):
    """Declare one perl_binary per perlasm script, plus a filegroup `name` listing them.

    Args:
        name: Name of the filegroup collecting the binaries.
        scripts: perlasm script paths (relative to the OpenSSL root).
        data: Files the scripts read relative to their own location at run
            time, e.g. crypto/perlasm/*-xlate.pl and ecp_nistz256_table.c.
            Included in every binary's runfiles.
        **kwargs: Forwarded to each perl_binary and the filegroup (e.g. tags).
    """
    for script in scripts:
        perl_binary(
            name = openssl_perlasm_tool_name(script),
            srcs = [script],
            main = script,
            data = data,
            **kwargs
        )
    native.filegroup(
        name = name,
        srcs = [":" + openssl_perlasm_tool_name(script) for script in scripts],
        **kwargs
    )

def _openssl_perlasm_impl(ctx):
    cc_toolchain = ctx.exec_groups[_EXEC_GROUP].toolchains[CC_TOOLCHAIN_TYPE].cc

    feature_configuration = cc_common.configure_features(
        ctx = ctx,
        cc_toolchain = cc_toolchain,
        requested_features = ctx.features,
        unsupported_features = ctx.disabled_features,
    )

    # The scripts run $CC (version, assembler version, predefined macros) to
    # pick instruction-set paths. Hand them exactly the configured compiler,
    # with the environment the toolchain declares for it, so the probe sees
    # the target toolchain rather than whatever is on the host.
    env = dict(cc_common.get_environment_variables(
        feature_configuration = feature_configuration,
        action_name = ACTION_NAMES.c_compile,
        variables = cc_common.empty_variables(),
    ))
    cc_path = cc_common.get_tool_for_action(
        feature_configuration = feature_configuration,
        action_name = ACTION_NAMES.c_compile,
    )

    # Perl's backticks go through cmd.exe on Windows, which reads the "/" after
    # a drive letter as a switch ("'C:' is not recognized ...").
    if len(cc_path) > 1 and cc_path[1] == ":":
        cc_path = '"' + cc_path.replace("/", "\\") + '"'
    env["CC"] = cc_path

    outs_as_files = []
    for tools_to_outs in [ctx.attr.scripts, ctx.attr.scripts_second_output]:
        for tool, out in tools_to_outs.items():
            out_file = ctx.actions.declare_file(out)
            outs_as_files.append(out_file)

            # The compiler probes are written for gcc/clang on a POSIX shell;
            # elsewhere (cl.exe through cmd.exe) they fail on stderr, and
            # upstream's build just lets that scroll by. quiet_run keeps the
            # output for failures only, so consumers never see it on success.
            ctx.actions.run(
                executable = ctx.executable._quiet_run,
                arguments = [tool[DefaultInfo].files_to_run.executable.path, ctx.attr.assembly_flavor, out_file.path],
                inputs = cc_toolchain.all_files,
                outputs = [out_file],
                env = env,
                tools = [tool[DefaultInfo].files_to_run],
                mnemonic = "OpenSSLPerlasm",
                # exec_group decides where the action runs; toolchain records
                # which of that group's toolchains it uses (the probed C++
                # compiler). Bazel requires the two to agree.
                exec_group = _EXEC_GROUP,
                toolchain = CC_TOOLCHAIN_TYPE,
            )

    if not outs_as_files:
        return [
            DefaultInfo(files = depset()),
            CcInfo(compilation_context = cc_common.create_compilation_context()),
        ]

    return [
        DefaultInfo(files = depset(outs_as_files)),
        CcInfo(
            compilation_context = cc_common.create_compilation_context(
                direct_private_headers = outs_as_files,
            ),
        ),
    ]

openssl_perlasm = rule(
    implementation = _openssl_perlasm_impl,
    doc = "Run OpenSSL perlasm scripts (wrapped as perl_binary targets) to produce assembly for one flavour.",
    attrs = {
        "assembly_flavor": attr.string(
            doc = "perlasm output flavour (e.g. elf, ios64, masm), passed to every script.",
        ),
        "scripts": attr.label_keyed_string_dict(
            doc = "perlasm perl_binary (see openssl_perlasm_tools) -> assembly file it writes.",
            cfg = config.exec(exec_group = _EXEC_GROUP),
            providers = [DefaultInfo],
        ),
        "scripts_second_output": attr.label_keyed_string_dict(
            doc = "Like scripts, for scripts run a second time to write a different file (e.g. sha512-x86_64.pl also writes sha256).",
            cfg = config.exec(exec_group = _EXEC_GROUP),
            providers = [DefaultInfo],
        ),
        "_quiet_run": attr.label(
            cfg = config.exec(exec_group = _EXEC_GROUP),
            executable = True,
            default = Label("//bazel:quiet_run"),
        ),
    },
    exec_groups = {
        _EXEC_GROUP: exec_group(toolchains = use_cc_toolchain()),
    },
    fragments = ["cpp"],
)
