"""OpenSSL Perl template processing at build time.

Generates files from OpenSSL's util/dofile.pl templates (.h.in, .c.in,
.inc.in), DER table generators, progs.pl, and mkbuildinf.pl. Template
processing is batched into a single Perl invocation via batch_dofile to
avoid per-template process-creation overhead on Windows. Uses
redirect_stdout for single-output actions (mkbuildinf, progs).

The template list is not hardcoded here: it is generated into
//bazel/constants:templates.bzl from OpenSSL's configdata.pm, so it tracks
whatever OpenSSL version the overlay was generated for.
"""

load("//bazel/constants:generated_srcs.bzl", "COMMON_GENERATED_CRYPTO_SRCS", "GENERATED_CRYPTO_EXTRA_SRCS")
load("//bazel/constants:templates.bzl", "DOFILE_HDR_TEMPLATES", "DOFILE_SRC_TEMPLATES")

# Fixed epoch for SOURCE_DATE_EPOCH to ensure reproducible timestamps.
_HERMETIC_ENV = {"SOURCE_DATE_EPOCH": "443779200"}

def _run_dofile(ctx, out_files_list):
    """Run batch_dofile once for all templates."""
    inputs = []
    outputs = []
    args = ctx.actions.args()

    # The --in/--out pairs for all templates exceed the Windows cmd.exe
    # command-line limit, so always pass them via a params file, which
    # batch_dofile.pl expands.
    args.use_param_file("@%s", use_always = True)
    args.set_param_file_format("multiline")

    for target, output in ctx.attr.templates_map.items():
        template_file = target.files.to_list()[0]
        out_file = ctx.actions.declare_file(output)
        inputs.append(template_file)
        outputs.append(out_file)
        out_files_list.append(out_file)
        args.add("--in=" + template_file.path)
        args.add("--out=" + out_file.path)

    ctx.actions.run(
        executable = ctx.executable._batch_dofile,
        arguments = [args],
        inputs = inputs,
        outputs = outputs,
        mnemonic = "OpenSSLDofile",
        progress_message = "Generating %d template files" % len(outputs),
        toolchain = None,
    )

def _run_progs(ctx, flag, out_path):
    """Run the progs_gen perl_binary via redirect_stdout."""
    out = ctx.actions.declare_file(out_path)
    args = ctx.actions.args()
    args.add(ctx.executable._progs_gen)
    args.add(out)
    args.add("--")
    args.add(flag)
    args.add("apps/openssl")
    ctx.actions.run(
        executable = ctx.executable._redirect_stdout,
        arguments = [args],
        outputs = [out],
        tools = [
            ctx.attr._progs_gen[DefaultInfo].files_to_run,
        ],
        env = _HERMETIC_ENV,
        mnemonic = "OpenSSLProgs",
        progress_message = "Generating %s" % out.short_path,
        toolchain = None,
    )
    return out

def _openssl_gen_impl(ctx):
    crypto_outs = []
    app_outs = []

    if ctx.attr.mode == "hdrs":
        _run_dofile(ctx, crypto_outs)

        buildinf = ctx.actions.declare_file("crypto/buildinf.h")
        crypto_outs.append(buildinf)
        buildinf_args = ctx.actions.args()
        buildinf_args.add(ctx.executable._mkbuildinf)
        buildinf_args.add(buildinf)
        buildinf_args.add("--")
        buildinf_args.add("bazel")
        buildinf_args.add("bazel")
        ctx.actions.run(
            executable = ctx.executable._redirect_stdout,
            arguments = [buildinf_args],
            outputs = [buildinf],
            tools = [
                ctx.attr._mkbuildinf[DefaultInfo].files_to_run,
            ],
            env = _HERMETIC_ENV,
            mnemonic = "OpenSSLBuildinf",
            progress_message = "Generating %s" % buildinf.short_path,
            toolchain = None,
        )

        app_outs.append(_run_progs(ctx, "-H", "apps/progs.h"))

    elif ctx.attr.mode == "srcs":
        _run_dofile(ctx, crypto_outs)

        app_outs.append(_run_progs(ctx, "-C", "apps/progs.c"))

    return [
        DefaultInfo(files = depset(crypto_outs)),
        OutputGroupInfo(app = depset(app_outs)),
    ]

_openssl_gen = rule(
    implementation = _openssl_gen_impl,
    doc = """Generates OpenSSL headers and sources from Perl templates at build time.

All tools are exec-configured attributes (perl_binary targets), not toolchains,
so actions pass toolchain = None for --incompatible_auto_exec_groups.

In "hdrs" mode: processes .h.in dofile templates, generates crypto/buildinf.h,
and produces apps/progs.h (in the "app" output group).

In "srcs" mode: processes .c.in dofile templates and produces apps/progs.c
(in the "app" output group).

Template outputs go into DefaultInfo; app outputs go into OutputGroupInfo("app").""",
    attrs = {
        "mode": attr.string(
            mandatory = True,
            values = ["hdrs", "srcs"],
            doc = "Generation mode: 'hdrs' for headers + buildinf + progs.h, " +
                  "'srcs' for sources + progs.c.",
        ),
        "templates_map": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Map of .in template file labels to their canonical output paths.",
        ),
        "_batch_dofile": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//bazel:batch_dofile"),
        ),
        "_mkbuildinf": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//:mkbuildinf"),
        ),
        "_progs_gen": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//:progs_gen"),
        ),
        "_redirect_stdout": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//bazel:redirect_stdout"),
        ),
    },
)

def _src_templates_for(outputs):
    """Subset of DOFILE_SRC_TEMPLATES (template -> output) producing the given outputs."""
    wanted = {out: None for out in outputs}
    return {tmpl: out for tmpl, out in DOFILE_SRC_TEMPLATES.items() if out in wanted}

def _src_templates_select():
    """Per-configuration source templates, mirroring the libcrypto srcs select in //:BUILD.

    Only the generated sources Configure lists for a platform are rendered and
    compiled; the rest (e.g. Windows-only providers) are left out exactly as
    OpenSSL's own build would.
    """
    no_asm = COMMON_GENERATED_CRYPTO_SRCS + GENERATED_CRYPTO_EXTRA_SRCS["no_asm"]
    branches = {
        "//configs:_asm_" + config: _src_templates_for(COMMON_GENERATED_CRYPTO_SRCS + extra)
        for config, extra in GENERATED_CRYPTO_EXTRA_SRCS.items()
        if config != "no_asm"
    }
    branches["//configs:_no_asm_fallback"] = _src_templates_for(no_asm)
    branches["//conditions:default"] = _src_templates_for(no_asm)
    return select(branches)

def openssl_perl_genrule(*, name, mode = None, **kwargs):
    """Generate platform-independent OpenSSL files from Perl templates.

    Args:
        name: Target name.
        mode: "hdrs" or "srcs". If None, inferred from name suffix.
        **kwargs: Additional keyword arguments.
    """
    if mode == None:
        if name.endswith("_hdrs"):
            mode = "hdrs"
        elif name.endswith("_srcs"):
            mode = "srcs"
        else:
            fail("Cannot infer mode from name '{}'; pass mode explicitly".format(name))

    if mode == "hdrs":
        _openssl_gen(
            name = name,
            mode = "hdrs",
            templates_map = DOFILE_HDR_TEMPLATES,
            **kwargs
        )
    elif mode == "srcs":
        _openssl_gen(
            name = name,
            mode = "srcs",
            templates_map = _src_templates_select(),
            **kwargs
        )
    else:
        fail("mode must be 'hdrs' or 'srcs', got: " + mode)
