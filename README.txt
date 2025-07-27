To run the build from command line, ensure that you have docker installed and are in the backend_proto directory, 
then type "make up" which will expose the backend API on http://localhost:8000/graphql which you can put into your browser
to see the queries which you can run. Testing still in progress, dont expect too much :)

can now:
- create user
- create site
- create post
- get site by site id
- get user by ID

example user id is 4
example historical site id is 6
there is an example post attatched to the historical site (returned when querying sites)

here is query to get a site, and the posts that reference it:
query MyQuery {
  site(id: 6) {
    id
    posts {
      author {
        id
        name
      }
      likes
      dislikes
      content
      title
      id
      siteId
      userId
    }
    description
    dislikes
    likes
    title
  }
}


if you get error that says no env file 

use command: export ENV_FILE = .env.local
then type make up