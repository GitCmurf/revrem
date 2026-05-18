            commit=profiles.CommitConfig(
                enabled=True,
                harness="codex",
                message_model="fast-commit",
            ),
        ),
    )
    args = MODULE.parse_args(["--profile", "final-pr", "--base", "main"])

    config, _summary_format = MODULE.build_loop_config(args, tmp_path)
    assert config.commit_message_harness == "codex"
    assert config.commit_message_model == "fast-commit"
