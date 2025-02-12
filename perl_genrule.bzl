"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

load("@rules_cc//cc:defs.bzl", "CcInfo", "cc_common")

def combine_list_of_lists(list_of_lists):
    final_list = []
    for lst in list_of_lists:
        final_list = final_list + lst
    return final_list

def get_binary_invocation_based_on_cpu(is_nix):
    if is_nix:
        return "perl"
    else:
        return "perl.exe"

def strip_prefix_from_out_file(prefix, out_file):
    return out_file.split(prefix)

def run_generation(ctx, src, out, binary_invocation, additional_srcs):
    """Run the generation command.

    Args:
        ctx: The context object from bazel.
        src: The source target.
        out: The output target.
        binary_invocation: The binary to run to do generation.
        additional_srcs: The other perl scripts needed in generation.
    Returns:
        The output target as a file. Should only be one.
    """
    out_as_file = ctx.actions.declare_file(out)
    src_files = src.files
    for src_as_file in src_files.to_list():
        ctx.actions.run_shell(
            inputs = [src_as_file] + additional_srcs,
            outputs = [out_as_file],
            command = "{} {} nasm {}".format(binary_invocation, src_as_file.path, out_as_file.path),
            mnemonic = "GenerateAssemblyFromPerlScripts",
            progress_message = "Generating file {} from script {}".format(out_as_file.path, src_as_file.path),
            toolchain =
                "@rules_perl//:current_toolchain",
        )
    return out_as_file

def _perl_genrule_impl(ctx):
    binary_invocation = get_binary_invocation_based_on_cpu(ctx.attr.is_nix)
    out_files = []
    additional_srcs = combine_list_of_lists([src.files.to_list() for src in ctx.attr.additional_srcs])

    for src, out in ctx.attr.srcs_to_outs.items():
        if not src in ctx.attr.srcs_to_outs_exclude.keys():
            out_as_file = run_generation(ctx, src, out, binary_invocation, additional_srcs)
            out_files.append(out_as_file)
    for src, out in ctx.attr.srcs_to_outs_dupes.items():
        if not src in ctx.attr.srcs_to_outs_exclude.keys():
            out_as_file = run_generation(ctx, src, out, binary_invocation, additional_srcs)
            out_files.append(out_as_file)

    all_out_files = []

    cp_file = ctx.file._copy_file_script

    output_prefix = ""
    for out_file in out_files:
        stripped_prefix_out_file = strip_prefix_from_out_file("{}/".format(ctx.genfiles_dir.path), out_file.path)
        final_out_file = ctx.actions.declare_file(stripped_prefix_out_file)

        ctx.actions.run(
            inputs = [out_file],
            outputs = [final_out_file],
            executable = cp_file,
            arguments = [output_prefix, out_file.path, ctx.genfiles_dir.path],
            mnemonic = "CopyFilesToDirFromPerlGenrule",
            progress_message = "Copying files to directory from perl genrule",
        )

        all_out_files.append(final_out_file)

    all_out_files = all_out_files + out_files

    runfiles = ctx.runfiles(files = all_out_files)

    cc_info = CcInfo(
        compilation_context = cc_common.create_compilation_context(headers = depset(all_out_files)),
    )
    return [DefaultInfo(files = depset(all_out_files), runfiles = runfiles), cc_info]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        # Additional sources needed by the generation scripts.
        "additional_srcs": attr.label_list(allow_files = True, doc = "List of other input files used by the main input files."),
        # We need to know what os this is running on.
        "is_nix": attr.bool(doc = "Whether this is mac or linux or not."),
        # We need to know what architecture we are running on.
        "is_x86": attr.bool(doc = "Whether this is on arm64 or x86_64."),
        # The name of the repo to output to.
        "repo_name": attr.string(),
        # The dict of srcs to their outs.
        "srcs_to_outs": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files from their source script."),
        # The dicts of srcs to their outs when they are dupes from the first dict.
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files where the source is dupe from the first dict."),
        # The dict of srcs to their outs when they are known to be problematic for some reason. And can be safely excluded.
        "srcs_to_outs_exclude": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files that need to be excluded."),
        # We want to copy the files to an accessible place so they can be used in other rules.
        # The script is erroneously named because it actually copies.
        "_copy_file_script": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = "@openssl-generated-overlay//:move_file_and_strip_prefix.sh",
        ),
    },
)
