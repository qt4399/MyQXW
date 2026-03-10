
#--------------------------------------------------------------------------------

import readline
from init import build_agent, run_stream, build_input,  _iter_text_fragments
#--------------------------------------------------------------------------------

#---------------------------------------------------------------------------------

def main() -> None:
    agent = build_agent()
    while True:
        question=input("用户：")
        user_prompt = (
            f"{question}"
        )
        run_stream(agent, user_prompt)

if __name__ == "__main__":
    main()