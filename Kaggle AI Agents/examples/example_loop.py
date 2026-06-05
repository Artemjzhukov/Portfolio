# This agent runs ONCE at the beginning to create the first draft.
initial_writer_agent = Agent(
    name="InitialWriterAgent",
    model=Gemini(
        model="gemini-2.5-flash-lite",
        retry_options=retry_config
    ),
    instruction="""Based on the user's prompt, write the first draft of a short story (around 100-150 words).
    Output only the story text, with no introduction or explanation.""",
    output_key="current_story",  # Stores the first draft in the state.
)

print("✅ initial_writer_agent created.")

# This agent's only job is to provide feedback or the approval signal. It has no tools.
critic_agent = Agent(
    name="CriticAgent",
    model=Gemini(
        model="gemini-2.5-flash-lite",
        retry_options=retry_config
    ),
    instruction="""You are a constructive story critic. Review the story provided below.
    Story: {current_story}
    
    Evaluate the story's plot, characters, and pacing.
    - If the story is well-written and complete, you MUST respond with the exact phrase: "APPROVED"
    - Otherwise, provide 2-3 specific, actionable suggestions for improvement.""",
    output_key="critique",  # Stores the feedback in the state.
)

print("✅ critic_agent created.")

# This is the function that the RefinerAgent will call to exit the loop.
def exit_loop():
    """Call this function ONLY when the critique is 'APPROVED', indicating the story is finished and no more changes are needed."""
    return {"status": "approved", "message": "Story approved. Exiting refinement loop."}


print("✅ exit_loop function created.")

# This agent refines the story based on critique OR calls the exit_loop function.
refiner_agent = Agent(
    name="RefinerAgent",
    model=Gemini(
        model="gemini-2.5-flash-lite",
        retry_options=retry_config
    ),
    instruction="""You are a story refiner. You have a story draft and critique.
    
    Story Draft: {current_story}
    Critique: {critique}
    
    Your task is to analyze the critique.
    - IF the critique is EXACTLY "APPROVED", you MUST call the `exit_loop` function and nothing else.
    - OTHERWISE, rewrite the story draft to fully incorporate the feedback from the critique.""",
    output_key="current_story",  # It overwrites the story with the new, refined version.
    tools=[
        FunctionTool(exit_loop)
    ],  # The tool is now correctly initialized with the function reference.
)

print("✅ refiner_agent created.")

# The LoopAgent contains the agents that will run repeatedly: Critic -> Refiner.
story_refinement_loop = LoopAgent(
    name="StoryRefinementLoop",
    sub_agents=[critic_agent, refiner_agent],
    max_iterations=2,  # Prevents infinite loops
)

# The root agent is a SequentialAgent that defines the overall workflow: Initial Write -> Refinement Loop.
root_agent = SequentialAgent(
    name="StoryPipeline",
    sub_agents=[initial_writer_agent, story_refinement_loop],
)

print("✅ Loop and Sequential Agents created.")


runner = InMemoryRunner(agent=root_agent)
response = await runner.run_debug(
    "Write a short story about a lighthouse keeper who discovers a mysterious, glowing map"
)

'''
### Created new session: debug_session_id

User > Write a short story about a lighthouse keeper who discovers a mysterious, glowing map
InitialWriterAgent > Elias traced the salt-worn grooves of the lighthouse stairs, a familiar comfort in the vast, lonely ocean. Tonight, the storm raged with unusual ferocity, waves lashing the tower like angry fists. A sudden, blinding flash of blue light erupted from his desk. He’d been sorting through old maritime charts, seeking solace in their faded lines. But this was no ordinary light. It pulsed, emanating from a rolled parchment he’d never seen before. Unfurling it carefully, Elias gasped. A map, detailed and intricate, glowed with an otherworldly luminescence. Not of any known sea, but of constellations, with strange symbols marking points of unknown significance. He felt a pull, an ancient call from the glowing ink. The lighthouse, his solitary sentinel, suddenly felt like the edge of a much larger world.
CriticAgent > Your story presents a compelling hook with a strong sense of atmosphere and mystery. Here are a few suggestions to enhance it:

1.  **Show, Don't Just Tell Elias's Solitude:** While the storm and the lighthouse naturally evoke loneliness, consider adding a brief detail that *shows* Elias's isolation. For example, a quick thought about the last time he spoke to someone, or a small habit that underscores his solitary existence, would deepen the reader's connection to his character before the extraordinary event.

2.  **Elaborate on the "Pull" and "Ancient Call":** The sentence "He felt a pull, an ancient call from the glowing ink" is intriguing. To make this more impactful, you could hint at what that pull feels like. Is it physical, like a magnetic force? Is it an emotional yearning? Does it manifest as a whisper in his mind, or a stirring in his soul? A little more sensory detail here would amplify the sense of destiny or destiny.

3.  **Strengthen the Contrast Between Familiar and Unfamiliar:** You've done a good job contrasting the familiar lighthouse stairs with the strange map. To further emphasize this, consider adding a sentence that highlights how the *ordinary* lighthouse, his anchor to reality, is now juxtaposed with this cosmic discovery. For instance, you could describe the familiar beam of the lighthouse cutting through the storm, and then contrast it with the new, internal "light" emanating from the map, suggesting it's illuminating a different kind of reality.
RefinerAgent > Elias traced the salt-worn grooves of the lighthouse stairs, a familiar comfort in the vast, lonely ocean. He hadn't spoken to another soul in weeks, his only companions the creaking timbers and the mournful cry of the gulls. Tonight, the storm raged with unusual ferocity, waves lashing the tower like angry fists. A sudden, blinding flash of blue light erupted from his desk. He’d been sorting through old maritime charts, seeking solace in their faded lines. But this was no ordinary light. It pulsed, emanating from a rolled parchment he’d never seen before. Unfurling it carefully, Elias gasped. A map, detailed and intricate, glowed with an otherworldly luminescence. Not of any known sea, but of constellations, with strange symbols marking points of unknown significance. He felt a physical tug, a magnetic force drawing him closer to the parchment, accompanied by a whisper in the back of his mind, an ancient call from the glowing ink. The steady, familiar beam of the lighthouse swept across the tumultuous sea, an anchor to his reality, while the map’s internal light seemed to promise a reality far beyond. The lighthouse, his solitary sentinel, suddenly felt like the edge of a much larger, more mysterious world.
CriticAgent > APPROVED
WARNING:google_genai.types:Warning: there are non-text parts in the response: ['function_call'], returning concatenated text result from text parts. Check the full candidates.content.parts accessor to get the full model response.
'''