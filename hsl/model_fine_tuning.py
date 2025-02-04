# -*- coding: utf-8 -*-
"""model_fine_tuning(발표).ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1fqPkLRHPWKnt4l4n5i2uUke5ptPptmhV
"""

from google.colab import drive
drive.mount('/content/drive')

!pip install -q transformers datasets tensorboard wandb accelerate==0.26.1 peft==0.8.2 bitsandbytes==0.42.0 transformers==4.37.2 trl==0.7.10

from datasets import load_dataset
import os
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    pipeline,
    logging,
)
from peft import LoraConfig
from trl import SFTTrainer
from transformers import TextStreamer
from huggingface_hub import login
import tensorboard
import wandb

dataset = load_dataset("Smoked-Salmon-s/empathetic_dialogues_ko", split="train")

filtered_dataset = dataset.filter(lambda example: example['type'] == 'single')

def combine_texts(example):
    example['text'] = '<s>[INST] '+ example['instruction'] + ' [/INST] ' + example['output'] + ' </s>'
    return example

processed_dataset = filtered_dataset.map(combine_texts)

print(dataset)
print(dataset[0])
print(filtered_dataset)
print(filtered_dataset[0])
print(processed_dataset)
print(processed_dataset[0])
print(processed_dataset[0]['text'])

base_model = "nlpai-lab/KULLM3"

compute_dtype = getattr(torch, "float16")

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=compute_dtype,
    bnb_4bit_use_double_quant=False,
)

# load_in_4bit: we are loading the base model with a 4-bit quantization, so we are setting this value to True.
# bnb_4bit_use_double_quant: We also want double quantization so that even the quantization constant is quantized. So we are setting this to True.
# bnb_4bit_quant_type: We are setting this to nf4.
# bnb_4bit_compute_dtype: and the compute datatype we are setting to float16

model = AutoModelForCausalLM.from_pretrained(
    base_model,
    quantization_config=quant_config,
    device_map={"": 0}
)
model.config.use_cache = False
model.config.pretraining_tp = 1

tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

# Commented out IPython magic to ensure Python compatibility.
from huggingface_hub import notebook_login
# Log in to HF Hub
notebook_login()

wandb.login()
# %env WANDB_PROJECT=kullum3-fine-tuning

peft_params = LoraConfig(
    lora_alpha=16,
    lora_dropout=0.1,
    r=64,
    bias="none",
    task_type="CAUSAL_LM",
)

# lora_alpha: scaling factor for the weight matrices. alpha is a scaling factor that adjusts the magnitude of the combined result (base model output + low-rank adaptation). We have set it to 16. You can find more details of this in the LoRA paper here.
# lora_dropout: dropout probability of the LoRA layers. This parameter is used to avoid overfitting. This technique basically drop-outs some of the neurons during both forward and backward propagation, this will help in removing dependency on a single unit of neurons. We are setting this to 0.1 (which is 10%), which means each neuron has a dropout chance of 10%.
# r: This is the dimension of the low-rank matrix, Refer to Part 1 of this blog for more details. In this case, we are setting this to 64 (which effectively means we will have 512x64 and 64x512 parameters in our LoRA adapter.
# bias: We will not be training the bias in this example, so we are setting that to “none”. If we have to train the biases, we can set this to “all”, or if we want to train only the LORA biases then we can use “lora_only”
# task_type: Since we are using the Causal language model, the task type we set to CAUSAL_LM.

peft_model = get_peft_model(model, peft_params)

dir(peft_model)

peft_model.print_trainable_parameters()

training_params = TrainingArguments(
    output_dir="./results",
    num_train_epochs=1,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=2,
    optim="paged_adamw_32bit",
    save_steps=1000,
    logging_steps=100,
    learning_rate=2e-5,
    weight_decay=0.001,
    fp16=True,
    bf16=False,
    max_grad_norm=0.3,
    max_steps=-1,
    warmup_ratio=0.03,
    group_by_length=True,
    lr_scheduler_type="constant",
    report_to="wandb",
    seed=42
)

# output_dir: Output directory where the model predictions and checkpoints will be stored
# num_train_epochs=3: Number of training epochs
# per_device_train_batch_size=4: Batch size per GPU for training
# gradient_accumulation_steps=2: Number of update steps to accumulate the gradients for
# gradient_checkpointing=True: Enable gradient checkpointing. Gradient checkpointing is a technique used to reduce memory consumption during the training of deep neural networks, especially in situations where memory usage is a limiting factor. Gradient checkpointing selectively re-computes intermediate activations during the backward pass instead of storing them all, thus performing some extra computation to reduce memory usage.
# optim=”paged_adamw_32bit”: Optimizer to use, We will be using paged_adamw_32bit
# logging_steps=5: Log on to the console on the progress every 5 steps.
# save_strategy=”epoch”: save after every epoch
# learning_rate=2e-4: Learning rate
# weight_decay=0.001: Weight decay is a regularization technique used while training the models, to prevent overfitting by adding a penalty term to the loss function. Weight decay works by adding a term to the loss function that penalizes large values of the model’s weights.
# max_grad_norm=0.3: This parameter sets the maximum gradient norm for gradient clipping.
# warmup_ratio=0.03: The warm-up ratio is a value that determines what fraction of the total training steps or epochs will be used for the warm-up phase. In this case, we are setting it to 3%. Warm-up refers to a specific learning rate scheduling strategy that gradually increases the learning rate from its initial value to its full value over a certain number of training steps or epochs.
# lr_scheduler_type=”cosine”: Learning rate schedulers are used to adjust the learning rate dynamically during training to help improve convergence and model performance. We will be using the cosine type for the learning rate scheduler.
# report_to=”wandb”: We want to report our metrics to Weights and Bias
# seed=42: This is the random seed that is set during the beginning of the training.

trainer = SFTTrainer(
    model=model,
    train_dataset=processed_dataset,
    peft_config=peft_params,
    dataset_text_field="text",
    max_seq_length=None,
    tokenizer=tokenizer,
    args=training_params,
    packing=False,
)

trainer.train()

# Commented out IPython magic to ensure Python compatibility.
# %load_ext tensorboard
# %tensorboard --logdir ./results

#stop reporting to wandb
# wandb.finish()
# save model
trainer.save_model("/content/drive/MyDrive/Colab Notebooks/model")

output_dir = "/content/drive/MyDrive/Colab Notebooks/model/finetuned_model"
trainer.model.save_pretrained(output_dir)

streamer = TextStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

s = "제가 요즘 너무 불안해요. 앞으로 뭐가 될지 모르겠어요."
conversation = [{'role': 'user', 'content': s}]
inputs = tokenizer.apply_chat_template(
    conversation,
    tokenize=True,
    add_generation_prompt=True,
    return_tensors='pt').to("cuda")
_ = model.generate(inputs, streamer=streamer, max_new_tokens=150)

s = "제가 요즘 너무 불안해요. 앞으로 뭐가 될지 모르겠어요."
conversation = [{'role': 'user', 'content': s}]
inputs = tokenizer.apply_chat_template(
    conversation,
    tokenize=True,
    add_generation_prompt=True,
    return_tensors='pt').to("cuda")
_ = model.generate(inputs, streamer=streamer, max_new_tokens=200)

s = "이유는 나도 잘 모르겠는데, 밤에 잠들지 못하겠어"
conversation = [{'role': 'user', 'content': s}]
inputs = tokenizer.apply_chat_template(
    conversation,
    tokenize=True,
    add_generation_prompt=True,
    return_tensors='pt').to("cuda")
_ = model.generate(inputs, streamer=streamer, max_new_tokens=150)

