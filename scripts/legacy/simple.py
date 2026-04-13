import os
import random
import ollama

if __name__ == "__main__":
    # from prompts/... get each one from each list
    # open all folders
    # for each folder, get the file name and read the content
    # print the content
    prompt = []
    for folder in os.listdir("prompts"):
        
        if os.path.isdir(os.path.join("prompts", folder)):
            components =  os.listdir(os.path.join("prompts", folder))

            # random  select one file from the components
            file = random.choice(components)
            with open(os.path.join("prompts", folder, file), "r") as f:
                content = f.read()
            if "format" in folder:
                component_text = content
            else:
                response = ollama.chat(
                    model="llama3.1:8b",
                    messages=[
                        {
                            "role": "user",
                            "content": """Your task is to rewrite the sentence I provide.
                                        Rules:
                                        1. Output only the rewritten sentence.
                                        2. Do not include any explanations or additional text
                                        3. Do not add prefixes or suffixes such as "Rewritten sentence:".
                                        4. The output must be plain text only.
                                        5. Preserve the original meaning while expressing it in a different way.
                                        Sentence to rewrite:
                                        """ + content
                                }
                            ]
                        )
                component_text = response["message"]["content"]
            
            # name the file in number order
            with open(os.path.join("prompts", folder, str(len(components))), "w") as f:
                f.write(component_text)

            prompt.append(component_text)
    
    # suffle the prompt
    random.shuffle(prompt)
    print("\n".join(prompt))

    #rewrite the prompt to a single string
    with open(os.path.join("prompts", "prompt.txt"), "w") as f:
        f.write("\n".join(prompt))