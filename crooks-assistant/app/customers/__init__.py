"""Customers as the owner talks about them: found from what he remembers, told as one story.

George, 2 October 2026: "Clive should realise when I say look up this customer xyz the words it
records may not be the exact customer name, e.g. Alysa could be Alicia or Alcya or Alisya. Where
it can find an order that matches the rest of the context it should do so and not hinge on that
one point of evidence." And: "Clive should understand the history of this customer, through
emails where they are related, to orders and the whole broader Clive ecosystem."

    app/customers/names.py     how a name heard is held against a name on an order
    app/customers/when.py      "last week", "Tuesday", "the 28th" as a window of days
    app/customers/match.py     every fact he gave, scored together, and a verdict that says why
    app/customers/history.py   one customer's timeline: orders, shipping, refunds, email, and
                               what CLIVE itself recorded about them
    app/customers/payments.py  whether a refund has landed, in Shopify's own words

Everything in this package reads. Nothing here changes the shop, sends a message, or writes to
any record; the one change it leads to (a checkout link, app/families/checkout_link.py) is a
card on the action engine like every other, sent only by the owner's hold.
"""
