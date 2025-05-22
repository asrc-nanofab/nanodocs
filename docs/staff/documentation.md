# Documentation at the ASRC Nanofab Facility

May 22, 2025

This is going to be a write-up of our documentation at the ASRC Nanofabrication Facility. The reason that we're making changes in the documentation is that the way that we do things and the way that many labs do things is not sustainable. There's currently no versioning, there's no policy, there's no format, and in particular, there's no way to use this information in a useful way. That means that there's no way to easily make all the information that we have available to ourselves or to others—say our users as need be—in its current format. It's always clunky and needs to be redirected. What we want to have is a single place to house all of our documentations and the versioning for both ourselves and others. So that's what we're going to be defining here. 

The first thing to consider is what the base format going to be? One thing that AI typically uses is Markdown. It's a very lightweight markup language and it's very useful. However, not everybody is used to interacting with it and might not be comfortable.
So one of the decisions that I'm making here in this new program is to use Google Docs and Google Drive. There are reasons for this that I want to itemize:

- People know how to interact with Google and Google Docs
- Google Docs is simple formatting (though you can get fancy, it's not quite as complex as Microsoft Word)
- There are URLs that allow us to access the documentation programmatically, and Google has an API (application programming interface) to do so
- Google Docs has a versioning history
- Google Docs can easily convert a regular Microsoft documentation into Google Docs can also easily be converted into PDF files which can be used in other parts of our document pipeline

Other things to consider when making this documentation. We want one ground source of truth. We want one place where the original documents reside. But this place needs to be a place where people with the proper authorization can come in and modify the documentation. So it also needs to contain an interface. This is to say that there are many services that have document storage but not all of them have the ability to store the documents to be able to serve the documents by API or by URL and also simultaneously to be able to have an interface to be able to modify those documents. Google Docs satisfies all of those requirements. 

The one thing that Google Docs does not offer, which is important for us when users in the community want to reference these docs, is it doesn't have the ability to be able to bring up a document with an exact page number.

So many times when you're retrieving certain information from documentation, you will find that the URL or the source (if you're using a Google search engine) will actually return to you the page and the location of that page where the information is contained. The only thing that Google Docs would be able to do is to actually serve the entire document.

For this reason, we need to add an additional step in the pipeline where at a certain point in time (maybe this is weekly or any time a major version is made), we need to be able to add an aspect where that document is converted into a PDF and that there is a cloud-based storage that references these PDFs and the URLs to the PDFs. This is an additional step that needs to be done with Google Docs that may not typically need to be done with other document management tools and software's. 

## How to do this:

1.  Import all documentation into google drive with comprehensive formatiing that remains consistent

