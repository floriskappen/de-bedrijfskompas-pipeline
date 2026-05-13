# De Bedrijfskompas (pipeline)

## the problem

im currently following a masters degree in AI and i have a background in software development. ive worked in the field before so i have some experience. i know what i like and dont like. i relate heavily to the concept of ikigai applied to work and also the company i want to work at in the future, where i connect with a company where i can not just work professionally and earn money, but also where i feel passionate about the purpose of the company and it has a mission i care deeply about. so i want to try a different approach of finding a future job than to just look at generic job boards on linkedin or indeed (which i find very demotivating and uninspiring). because all those job and company descriptions on those platforms use marketing and generic recruiter terms. and even if you then click through to the company website, that also usually is filled with vague marketing buzzwords which leads to everything just bleeding together.

and another problem is that when looking at a job board you are looking vacancy-first. this is good for the companies but less good for the person looking for a job. you are just seeing the list of companies that have posted vacancies at that moment, and usually sponsored ones etc at the top. for me, its still quite a while before i graduate. and a job is a big decision. 

## the solution and goal

so instead of looking at job boards each week to see what new jobs and possible companies there are each time, i would like to just know what companies there are at in general (including those who are not hiring) and build up a list of the ones that i find interesting, and perhaps send open application or wait until one of them happens to post a job. this can be a months long process. but people usually stay at a job for years, so if you just keep track of the companies which you find interesting and discover new ones etc you can wait, there is no rush!

the idea is that this will lead to higher quality, better jobs for the ones looking for a job.

the company discovery process should be done in a way where we cut through the bullshit marketing texts on their website and extract what the company actually really does. this is specially important for smaller and newer companies like startups etc, to quickly scan through them. perhaps later we can also do ikigai-matching somehow.


## the pipeline part

this repo focuses on the pipeline. the project is made up of two sub-projects, each in their own repo, for now: frontend and pipeline.
the pipeline (this repo) ingests/scrapes/extracts data and transforms it. this runs independently.
the frontend is a simple static website which is built based on this data.

### architecture
python, offline batch pipeline, made up of multiple stages. intermediate data persisted between stages. so each stage has a clean input and output.
llms are used in the project for analysis. prompts live in prompts/ as a versioned file, loaded by name. no inline prompts in code.ever.

