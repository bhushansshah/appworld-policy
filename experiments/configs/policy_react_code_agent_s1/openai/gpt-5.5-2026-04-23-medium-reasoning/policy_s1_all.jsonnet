local experiment_prompts_path = std.extVar("APPWORLD_EXPERIMENT_PROMPTS_PATH");
local experiment_configs_path = std.extVar("APPWORLD_EXPERIMENT_CONFIGS_PATH");
local experiment_code_path = std.extVar("APPWORLD_EXPERIMENT_CODE_PATH");
{
    "type": "simplified",
    "config": {
        "agent": {
            "type": "simplified_react_code_agent",
            "model_config": {
                "client_name": "openai",
                "api_type": "responses",
                "name": "gpt-5.5-2026-04-23",
                "reasoning": {"effort": "medium"},
                "temperature": 1.0,
                "drop_reasoning_content": false,
                "cost_per_token": {"input_cache_hit": 5e-07, "input_cache_miss": 5e-06, "input_cache_write": 0.0, "output": 3e-05},
                "retry_after_n_seconds": 15,
                "use_cache": false,
                "max_retries": 100,
            },
            "appworld_config": {
                "random_seed": 100,
                "raise_on_extra_parameters": true,
            },
            "logger_config": {
                "color": true,
                "verbose": true,
            },
            "usage_tracker_config": {
                "max_cost_overall": 1000,
                "max_cost_per_task": 10,
                "max_output_tokens_per_task": 100000,
            },
            "prompt_file_path": experiment_prompts_path + "/policy_react_code_agent_s1/instructions.txt",
            "ignore_multiple_calls": true,
            "max_prompt_length": null,
            "max_output_length": null,
            "max_steps": 50,
            "log_lm_calls": true,
            "skip_if_finished": true,
        },
        "dataset": "policy_s1_all",
    },
    "metadata": {
        "model": {
            "file_name": "gpt-5.5-2026-04-23-medium-reasoning",
            "humanized_name": "Gpt 5.5 2026 04 23 Medium Reasoning",
            "precise_name": "gpt-5.5-2026-04-23",
            "creator": "openai",
            "provider": "openai",
        },
        "agent": {
            "file_name": "simplified_react_code_agent",
            "humanized_name": "ReAct Code Agent (policy prompt, setting 1)",
        },
    },
}