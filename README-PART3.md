Part 3: Eight business questions

1. For a 2 crore a BFSI account the Platform fee would be better approach. It would be fixed charge for the router and the deployment and plus for each model pass through. Outcome pricing would be a bit hard as companies have complaince guidelines. Blended per token would be like a self kill you can't say whether the router will pick the highest or the lowest. For the model pass through it would be clear for the compaines how much extra fee they are paying apart from the model but incase of Platform subscription its not possible.


2. Building the router is essential because it slashes unnecessary token costs and latency by stopping simple workloads from hitting expensive frontier models. 

In an enterprise VPC or air-gapped setup, the router also works as a compliance check. It runs locally, so the routing decision never goes over the internet, and it only sends sensitive requests to models hosted inside the customer's network.

3. It is Wrong for live voice agents and high-stakes workloads. A voice agent has to reply within roughly 300–500ms to feel natural, so an extra 120ms is a noticeable. For banks, legal and medical customers, the hardest 10% of queries is where the money and liability sit, so a 3% accuracy drop there costs more than the 55% saving.

In the contract we can mention:
 - giving an explicit toggle when to directly use a frontier model
 - voice skips the router or explicitly mention that there will be delay.

4. Router also handle the model failure if any of the model is down or occupied it can shift to different provider or equivalent model to provide the output.

not every task requires this much level of computation its like hiring an 10 years experience dev for creating GET endpoints (interns work - why wasting money). 

The Discovery Question:
What industry are you in, and is your workload genuinely critical enough that a simple classification or extraction task justifies paying frontier-model prices for every single request?


5. Where Sarvam wins: it owns the models it routes to. On Indic and code-switched traffic, routing lands on Sarvam's own models, which are better at Indian languages and cheaper to serve, so Sarvam keeps the margin which OpenRouter, Not Diamond can't. It also deploys the whole stack (router plus models) inside a customer's VPC or air-gapped rack

when it loses: Competitors like OpenRouter or Martian offer an expansive, plug-and-play catalog spanning hundreds of global models with robust multi-provider fallbacks. Currently Sarvam only has support of three open weight model which lacks the global model variety.

6. This question is missing in the docs

7. Segment would be Banks and insurers. They run huge call volumes in Hindi and regional languages. 

First workload: post-call summaries of collections and renewal calls. High volume, mostly easy-to-medium, Indic-heavy, and needed for compliance records. It is low risk as no customer is waiting on the reply.

proof would be the cost effetiveness and P95latency than the frontier models 

to scale the pilot to 10 crores, i would say i dont have idea for this (but assumption i would say if the summarizations scores were accurate then can expand to doc scanning and summarization)

8. Check the routing logs for that specific 5% of queries to identify why the classifier failed and immeditely shift the quries for that customer to much better frontier model so the quality is restored and bearing the cost. Also discuss with the team to give a tentative date for the resolution for the issue as soon as possible.



