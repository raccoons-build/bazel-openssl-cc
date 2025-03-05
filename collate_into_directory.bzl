"""Move files from one path to an output directory specified through a series of dicts
"""

def get_inputs_and_commands(mv_file, call_to_script, srcs_map, ctx, outdir):
    """Gets the input files and the commands to run

    Args: 
        mv_file: The move file to use on nix
        call_to_script: the formatted string to do replace on 
        srcs_map: map of sources to the outputs
        ctx: the current context
        outdir: the output directory
    Returns: 
        input_files: The input files to the run_shell
        copy_calls: The structured commands to run
    """

    copy_calls = []
    for (tgt, prefix) in srcs_map.items():
        output_prefix = None
        if tgt in ctx.attr.outs_prefix_map:
            output_prefix = ctx.attr.outs_prefix_map[tgt]

        for file in tgt[DefaultInfo].files.to_list():
            if ctx.attr.is_nix:
                copy_calls.append(
                    call_to_script.format(
                        script_path = mv_file.path,
                        outdir = outdir.path if not output_prefix else "{}/{}".format(outdir.path, output_prefix),
                        file = file.path,
                        prefix_to_strip = prefix if not file.path.startswith(ctx.genfiles_dir.path) else "{}/{}".format(ctx.genfiles_dir.path, prefix),
                    ),
                )
            else:
                copy_calls.append(
                    call_to_script.format(
                        outdir = outdir.path if not output_prefix else "{}/{}".format(outdir.path, output_prefix),
                        file = file.path,
                        prefix_to_strip = prefix if not file.path.startswith(ctx.genfiles_dir.path) else "{}/{}".format(ctx.genfiles_dir.path, prefix),
                    ),
                )
    mv_file_list = []
    if mv_file:
        mv_file_list.append(mv_file)
    input_files = depset(
        mv_file_list,
        transitive = [tgt[DefaultInfo].files for tgt in srcs_map.keys()],
    )

    return input_files, copy_calls

def _collate_into_directory_impl(ctx):
    out = "{}_out".format(ctx.attr.name)
    outdir = ctx.actions.declare_directory(out)
    mv_file = ctx.file._move_file_script

    call_to_script = """{script_path} {outdir} {file} {prefix_to_strip}"""
    call_to_script_windows = """ 
$clean_filepath = {file}.Substring({prefix_to_strip}.Length)

$clean_dirname = [System.IO.Path]::GetDirectoryName($clean_filepath)

$dest_path = Join-Path -Path {outdir} -ChildPath $clean_dirname
New-Item -ItemType Directory -Force -Path $dest_path

Copy-Item -Path {file} -Destination $dest_path -Recurse -Force
"""

    srcs_map = dict(ctx.attr.srcs_prefix_map)

    # If a user declares an output that is not in srcs, we still want to copy it.
    implicit_srcs_from_outs = {
        tgt: ""
        for (tgt, _) in ctx.attr.outs_prefix_map.items()
        if tgt not in srcs_map
    }
    srcs_map.update(implicit_srcs_from_outs)

    if ctx.attr.is_nix:
        input_files, copy_calls = get_inputs_and_commands(mv_file, call_to_script, srcs_map, ctx, outdir)

        ctx.actions.run_shell(
            inputs = input_files,
            outputs = [outdir],
            command = "\n".join(copy_calls),
            mnemonic = "CopyFilesToDir",
            progress_message = "Copying files to directory",
        )
    else:
        input_files, copy_calls = get_inputs_and_commands(None, call_to_script_windows, srcs_map, ctx, outdir)

        ctx.actions.run_shell(
            inputs = input_files,
            outputs = [outdir],
            command = "\n".join(copy_calls),
            mnemonic = "CopyFilesToDirOnWindows",
            progress_message = "Copying files to directory on Windows",
        )
    runfiles = ctx.runfiles(files = [outdir])

    return [DefaultInfo(files = depset([outdir]), runfiles = runfiles)]

collate_into_directory = rule(
    implementation = _collate_into_directory_impl,
    doc = "Collate a set of files into a single directory, optionally manipulating subdirectories.",
    attrs = {
        "outs_prefix_map": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Map from target that provides files to prefix to use when placing the files, in addition to the relative directory remaining after stripping the prefix. If a key appears in this map but not the `srcs_prefix_map`, it will be implicitly added as a source.",
        ),
        "srcs_prefix_map": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Map from target that provides files to prefix to strip from those files.",
        ),
        # We need to know what os this is running on.
        "is_nix": attr.bool(doc = "Whether this is mac or linux or not."),
        "_move_file_script": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = "@openssl-generated-overlay//:move_file_and_strip_prefix.sh",
        ),
    },
)
