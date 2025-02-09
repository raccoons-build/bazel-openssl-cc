"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""
def _perl_genrule_impl(ctx):
    srcs_and_outputs_dict = {}
    for i in range(len(ctx.outs)):
        srcs_and_outputs_dict.add(ctx.srcs[i], ctx.outs[i])

    for src, out in srcs_and_outputs_dict.items():
        ctx.actions.run_shell(
            inputs = attr.srcs,
            outputs = attr.outs,
            command = "perl.exe {} nasm {}".foramt(src, out),
            mnemonic = "Generate files with perl",
            progress_message = "Generating file {} with perl from file {}".format(out, src),
            toolchains = [
                "@bazel_tools//tools/cpp:current_cc_toolchain",
                "@rules_perl//:current_toolchain",
            ],
        )
    runfiles = ctx.runfiles(files = attr.outs)

    return [DefaultInfo(files = depset(attr.outs), runfiles = runfiles)]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        "outs": attr.output_list(allow_files = [".s"], doc = "List of output files."),
        "srcs": attr.label_list(allow_files = [".pl"], doc = "List of input files"),
    },
)
