"""Move files from one path to an output directory specified through a series of dicts
"""

def _get_inputs_and_commands(mv_file, srcs_map, ctx, outdir, is_windows):
    """Gets the input files and the commands to run

    Args:
        mv_file: The move file to use on nix
        srcs_map: map of sources to the outputs
        ctx: the current context
        outdir: the output directory
        is_windows: Whether or not the exec platform is windows.
    Returns:
        input_files: The input files to the run_shell
        copy_calls: The structured commands to run
    """
    call_to_script = """{script_path} {outdir} {file} {prefix_to_strip}"""

    copy_calls = []
    for (tgt, prefix) in srcs_map.items():
        output_prefix = None
        if tgt in ctx.attr.outs_prefix_map:
            output_prefix = ctx.attr.outs_prefix_map[tgt]

        for file in tgt[DefaultInfo].files.to_list():
            script_path = mv_file.path
            outdir_path = outdir.path if not output_prefix else "{}/{}".format(outdir.path, output_prefix.lstrip("/"))
            file_path = file.path
            prefix_to_strip = prefix if not file.path.startswith(ctx.genfiles_dir.path) else "{}/{}".format(ctx.genfiles_dir.path, prefix)

            # Update file paths
            if is_windows:
                script_path = script_path.replace("/", "\\")
                outdir_path = outdir_path.replace("/", "\\")
                file_path = file_path.replace("/", "\\")
                prefix_to_strip = prefix_to_strip.replace("/", "\\")

            copy_calls.append(
                call_to_script.format(
                    script_path = script_path,
                    outdir = outdir_path,
                    file = file_path,
                    prefix_to_strip = prefix_to_strip,
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

_WINDOWS_TEMPLATE = """\
@ECHO OFF
{}
"""

_UNIX_TEMPLATE = """\
#!/usr/bin/env bash
set -euo pipefail
{}
"""

def _collate_into_directory_impl(ctx):
    outdir = ctx.actions.declare_directory("{}_out".format(ctx.attr.name))
    mv_file = ctx.file._move_file_script

    srcs_map = dict(ctx.attr.srcs_prefix_map)

    # If a user declares an output that is not in srcs, we still want to copy it.
    implicit_srcs_from_outs = {
        tgt: ""
        for (tgt, _) in ctx.attr.outs_prefix_map.items()
        if tgt not in srcs_map
    }
    srcs_map.update(implicit_srcs_from_outs)

    is_windows = ctx.executable._move_file_script.basename.endswith(".bat")
    input_files, copy_calls = _get_inputs_and_commands(mv_file, srcs_map, ctx, outdir, is_windows)

    action_runner = ctx.actions.declare_file("{}.action_runner.{}".format(ctx.label.name, "bat" if is_windows else "sh"))
    template = _WINDOWS_TEMPLATE if is_windows else _UNIX_TEMPLATE
    ctx.actions.write(
        output = action_runner,
        content = template.format("\n".join(copy_calls)),
        is_executable = True,
    )

    ctx.actions.run(
        inputs = input_files,
        executable = action_runner,
        outputs = [outdir],
        mnemonic = "OpenSSLCopyFilesToDir",
        progress_message = "Copying files to directory",
        use_default_shell_env = True,
    )

    return [
        DefaultInfo(
            files = depset([outdir]),
            runfiles = ctx.runfiles(files = [outdir]),
        ),
    ]

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
        "_move_file_script": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = "@openssl-generated-overlay//:move_file_and_strip_prefix",
        ),
    },
)
