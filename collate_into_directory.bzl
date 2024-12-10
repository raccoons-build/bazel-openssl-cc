def _collate_into_directory_impl(ctx):
    out = "{}_out".format(ctx.attr.name)
    outdir = ctx.actions.declare_directory(out)
    mv_file = ctx.file._move_file_script

    call_to_script = """{script_path} {outdir} {file} {prefix_to_strip}"""
    copy_calls = []
    srcs_map = dict(ctx.attr.srcs_prefix_map)

    # If a user declares an output that is not in srcs, we still want to copy it.
    implicit_srcs_from_outs = {
        tgt: ""
        for (tgt, _) in ctx.attr.outs_prefix_map.items()
        if tgt not in srcs_map
    }
    srcs_map.update(implicit_srcs_from_outs)

    for (tgt, prefix) in srcs_map.items():
        output_prefix = None
        if tgt in ctx.attr.outs_prefix_map:
            output_prefix = ctx.attr.outs_prefix_map[tgt]

        for file in tgt[DefaultInfo].files.to_list():
            copy_calls.append(
                call_to_script.format(
                    script_path = mv_file.path,
                    outdir = outdir.path if not output_prefix else "{}/{}".format(outdir.path, output_prefix),
                    file = file.path,
                    prefix_to_strip = prefix if not file.path.startswith(ctx.genfiles_dir.path) else "{}/{}".format(ctx.genfiles_dir.path, prefix),
                ),
            )

    input_files = depset(
        [mv_file],
        transitive = [tgt[DefaultInfo].files for tgt in srcs_map.keys()],
    )
    ctx.actions.run_shell(
        inputs = input_files,
        outputs = [outdir],
        command = "\n".join(copy_calls),
        mnemonic = "CopyFilesToDir",
        progress_message = "Copying files to directory",
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
        "_move_file_script": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = "@openssl-generated-overlay//:move_file_and_strip_prefix.sh",
        ),
    },
)
