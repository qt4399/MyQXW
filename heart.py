
#--------------------------------------------------------------------------------

import readline
from init import build_heart, run_heart, _iter_text_fragments
#--------------------------------------------------------------------------------

#---------------------------------------------------------------------------------
def main() -> None:
    agent = build_heart()
    while True:
        question="Boom"
        user_prompt = (
            f"{question}"
        )
        run_heart(agent, user_prompt)
        
if __name__ == "__main__":
    main()