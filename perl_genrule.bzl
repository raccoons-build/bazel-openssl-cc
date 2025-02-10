"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

def remove_path_and_type(file_name):
    wo_path = str(file_name).split("/")[-1]
    return wo_path.split(".")[0]

def find_source_for_out(output_file, possible_sources_list, srcs_to_outs_overrides):
    """Finds the source file for the given output file.

    Args:
        output_file: The .s file to generate
        possible_sources_list: All the .pl files we use to generate the .s
        srcs_to_outs_overrides: The dict of sources to outputs that are overriden
    Returns:
        The closest match by name of file or an error message
    """
    just_output_file = remove_path_and_type(output_file)

    # split on the path delimitter and period and compare the file names.
    for src in possible_sources_list:
        just_src_file = remove_path_and_type(src)

        if just_output_file == just_src_file:
            return src

    # If we dont find it by name  then try the override dict.
    for src in possible_sources_list:
        if src in srcs_to_outs_overrides.keys():
            return srcs_to_outs_overrides[src]

    return "Could not find source for output for {} from {} options".format(output_file, possible_sources_list)

def _perl_genrule_impl(ctx):
    srcs_and_outputs_dict = {}
    for i in range(len(ctx.attr.outs)):
        out = ctx.attr.outs[i]
        src = find_source_for_out(out, ctx.attr.srcs, ctx.attr.srcs_to_outs_overrides)

        srcs_and_outputs_dict[src] = out

    for src, out in srcs_and_outputs_dict.items():
        print("Source: {} Output: {}".format(src, out))
        src_as_file = ctx.actions.declare_file(str(src))
        out_as_file = ctx.actions.declare_file(str(out))
        ctx.actions.run_shell(
            inputs = [src_as_file],
            outputs = [out_as_file],
            command = "perl.exe {} nasm {}".format(src, out),
            mnemonic = "Generate files with perl",
            progress_message = "Generating file {} with perl from file {}".format(out, src),
            toolchain =
                "@rules_perl//:current_toolchain",
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
        # The dicts of srcs to their outs when they don't share a file name.
        "srcs_to_outs_overrides": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files that need to be explicitly made."),
    },
)
