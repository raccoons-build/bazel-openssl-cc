"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

def _perl_genrule_impl(ctx):
    srcs_and_outputs_dict = {}
    for i in range(len(ctx.attr.outs)):
        srcs_and_outputs_dict.add(ctx.attr.srcs[i], ctx.attr.outs[i])

    for src, out in srcs_and_outputs_dict.items():
        fixed_src = src.replace("\\", "/")
        fixed_out = out.replace("\\", "/")
        ctx.actions.run_shell(
            inputs = [fixed_src],
            outputs = [fixed_out],
            command = "perl.exe {} nasm {}".foramt(fixed_src, fixed_out),
            mnemonic = "Generate files with perl",
            progress_message = "Generating file {} with perl from file {}".format(fixed_out, fixed_src),
            toolchains = [
                "@bazel_tools//tools/cpp:current_cc_toolchain",
                "@rules_perl//:current_toolchain",
            ],
        )
    runfiles = ctx.runfiles(files = ctx.attr.outs)

    return [DefaultInfo(files = depset(ctx.attr.outs), runfiles = runfiles)]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        # We allow outs to be empty so when we don't generate anything for nix platforms
        # we don't get an error.
        "outs": attr.output_list(allow_empty = True, doc = "List of output files."),
        "srcs": attr.label_list(allow_files = [".pl"], doc = "List of input files"),
    },
)
